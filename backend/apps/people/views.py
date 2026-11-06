from django.db import transaction
from rest_framework import viewsets

from apps.accounts.roles import Role
from apps.org.models import Department
from common.audit import get_object_unit, record_audit
from common.scoping import ScopedViewSetMixin

from .models import Guardian, StaffProfile, Student
from .permissions import PeopleManagementPermission
from .serializers import GuardianSerializer, StaffProfileSerializer, StudentSerializer


class StudentViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = Student.objects.select_related("user", "department", "program").all()
    serializer_class = StudentSerializer
    permission_classes = (PeopleManagementPermission,)
    search_fields = ("registration_number", "first_name", "last_name", "email", "phone")
    ordering_fields = (
        "registration_number",
        "first_name",
        "last_name",
        "admission_year",
    )
    filterset_fields = ("department", "program", "admission_year", "is_active")


class StaffProfileViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = StaffProfile.objects.select_related("user", "department").all()
    serializer_class = StaffProfileSerializer
    permission_classes = (PeopleManagementPermission,)
    search_fields = ("user__email", "user__display_name", "job_title")
    filterset_fields = ("department", "is_active")

    def get_queryset(self):
        return super().get_queryset()


class GuardianViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Guardian.objects.select_related("student__department").all()
    serializer_class = GuardianSerializer
    permission_classes = (PeopleManagementPermission,)
    search_fields = ("full_name", "email", "phone", "student__registration_number")
    filterset_fields = ("student",)

    def get_queryset(self):
        queryset = super().get_queryset()
        if self.request.user.role == Role.STUDENT:
            return queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        student = serializer.validated_data["student"]
        if (
            self.request.user.role == Role.HOD
            and not Department.objects.filter(
                pk=student.department_id, role_scopes__user=self.request.user
            ).exists()
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage guardians in your departments.")
        if (
            self.request.user.role == Role.STUDENT
            and student.user_id != self.request.user.id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage your own guardians.")
        with transaction.atomic():
            guardian = serializer.save()
            record_audit(
                actor=self.request.user,
                action="created",
                obj=guardian,
                unit=get_object_unit(guardian),
                after=self.get_serializer(guardian).data,
            )

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        if (
            self.request.user.role == Role.HOD
            and not Department.objects.filter(
                pk=student.department_id, role_scopes__user=self.request.user
            ).exists()
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage guardians in your departments.")
        if (
            self.request.user.role == Role.STUDENT
            and student.user_id != self.request.user.id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage your own guardians.")
        before = self.get_serializer(serializer.instance).data
        with transaction.atomic():
            guardian = serializer.save()
            record_audit(
                actor=self.request.user,
                action="updated",
                obj=guardian,
                unit=get_object_unit(guardian),
                before=before,
                after=self.get_serializer(guardian).data,
            )

    def perform_destroy(self, instance):
        before = self.get_serializer(instance).data
        with transaction.atomic():
            instance.is_active = False
            instance.save(update_fields=("is_active", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="archived",
                obj=instance,
                unit=get_object_unit(instance),
                before=before,
                after=self.get_serializer(instance).data,
            )
