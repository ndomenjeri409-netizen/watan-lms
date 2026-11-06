from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.roles import Role
from common.scoping import ScopedViewSetMixin

from .models import Application, CourseAccess, Enrollment
from .permissions import ApplicationPermission, EnrollmentPermission
from .serializers import (
    ApplicationSerializer,
    ApproveApplicationResponseSerializer,
    CourseAccessSerializer,
    EnrollmentSerializer,
    RejectApplicationSerializer,
    TransitionEnrollmentSerializer,
)
from .services import (
    approve_application,
    record_public_application,
    reject_application,
    transition_enrollment,
)


class ApplicationViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Application.objects.select_related(
        "department", "program", "course", "student", "reviewed_by"
    ).all()
    serializer_class = ApplicationSerializer
    permission_classes = (ApplicationPermission,)
    http_method_names = ("get", "post", "head", "options")
    search_fields = ("first_name", "last_name", "email", "course__title")
    filterset_fields = ("status", "department", "program", "course")
    ordering_fields = ("created_at", "status")

    def get_permissions(self):
        if self.action == "create":
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        with transaction.atomic():
            application = serializer.save()
            record_public_application(application)

    @extend_schema(request=None, responses=ApproveApplicationResponseSerializer)
    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        application, student, enrollment = approve_application(
            self.get_object(), request.user
        )
        return Response(
            {
                "application": self.get_serializer(application).data,
                "student": {
                    "id": str(student.id),
                    "registration_number": student.registration_number,
                    "email": student.email,
                },
                "enrollment_id": str(enrollment.id),
            }
        )

    @extend_schema(request=RejectApplicationSerializer, responses=ApplicationSerializer)
    @action(detail=True, methods=("post",))
    def reject(self, request, pk=None):
        serializer = RejectApplicationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        application = reject_application(
            self.get_object(), request.user, serializer.validated_data.get("note", "")
        )
        return Response(self.get_serializer(application).data)


class EnrollmentViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Enrollment.objects.select_related(
        "student__user", "course", "approved_by"
    ).all()
    serializer_class = EnrollmentSerializer
    permission_classes = (EnrollmentPermission,)
    filterset_fields = ("status", "student", "course", "course__department")
    ordering_fields = ("created_at", "activated_at", "status")
    search_fields = (
        "student__registration_number",
        "student__first_name",
        "student__last_name",
        "course__title",
        "course__code",
    )

    @extend_schema(
        request=TransitionEnrollmentSerializer, responses=EnrollmentSerializer
    )
    @action(detail=True, methods=("post",))
    def transition(self, request, pk=None):
        enrollment = self.get_object()
        serializer = TransitionEnrollmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target = serializer.validated_data["status"]
        if request.user.role == Role.STUDENT and target != Enrollment.Status.CANCELLED:
            raise PermissionDenied("Students may only cancel their own enrollment.")
        if (
            request.user.role == Role.HOD
            and not enrollment.course.department.role_scopes.filter(
                user=request.user
            ).exists()
        ):
            raise PermissionDenied(
                "You may only manage enrollments in your departments."
            )
        enrollment = transition_enrollment(enrollment, target, request.user)
        return Response(self.get_serializer(enrollment).data)


class CourseAccessViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = CourseAccess.objects.select_related("student__user", "course").all()
    serializer_class = CourseAccessSerializer
    permission_classes = (EnrollmentPermission,)
    filterset_fields = ("student", "course", "is_active")
    search_fields = ("student__registration_number", "course__title", "course__code")

    def get_queryset(self):
        queryset = super().get_queryset()
        if (
            self.request.user.role == Role.HOD
            and not self.request.user.role_scopes.exists()
        ):
            return queryset.none()
        return queryset
