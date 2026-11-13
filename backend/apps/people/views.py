from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from apps.accounts.roles import Role
from common.audit import get_object_unit, record_audit
from common.scoping import ScopedViewSetMixin

from .models import Guardian, StaffProfile, Student
from .permissions import PeopleManagementPermission, may_manage_student
from .serializers import (
    EnrollStudentInUnitResultSerializer,
    EnrollStudentInUnitSerializer,
    GuardianSerializer,
    InviteStudentSerializer,
    StaffProfileSerializer,
    StudentDuplicateConflictSerializer,
    StudentDuplicateLookupResultSerializer,
    StudentDuplicateLookupSerializer,
    StudentImportResultSerializer,
    StudentImportSerializer,
    StudentRegistrationSerializer,
    StudentSerializer,
    StudentStatusSerializer,
    StudentTransferSerializer,
)
from .services import (
    change_student_status,
    enroll_student_in_unit,
    find_student_duplicates,
    import_student_csv,
    invite_student,
    lookup_student_duplicate,
    make_duplicate_lookup,
    register_student,
    transfer_student,
)


class StudentViewSet(
    ScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    queryset = (
        Student.objects.select_related(
            "user", "home_unit", "department", "program", "photo_file"
        )
        .prefetch_related("enrollments__course", "enrollments__class_group__course")
        .all()
    )
    serializer_class = StudentSerializer
    permission_classes = (PeopleManagementPermission,)
    search_fields = ("registration_number", "first_name", "last_name", "email", "phone")
    ordering_fields = (
        "registration_number",
        "first_name",
        "last_name",
        "admission_year",
    )
    filterset_fields = (
        "department",
        "program",
        "home_unit",
        "admission_year",
        "status",
        "is_active",
    )

    def get_serializer_class(self):
        if self.action == "create":
            return StudentRegistrationSerializer
        return super().get_serializer_class()

    @extend_schema(
        request=StudentRegistrationSerializer,
        responses={
            status.HTTP_201_CREATED: StudentSerializer,
            status.HTTP_409_CONFLICT: StudentDuplicateConflictSerializer,
        },
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        matches = find_student_duplicates(values)
        visible_ids = (
            Student.objects.for_user(request.user)
            .filter(pk__in=matches.values("pk"))
            .values_list("pk", flat=True)
        )
        visible_matches = list(
            matches.filter(pk__in=visible_ids).select_related("home_unit")
        )
        hidden_matches = matches.exclude(pk__in=visible_ids)
        confirm_duplicate = values.pop("confirm_duplicate", False)
        if hidden_matches.exists():
            token = make_duplicate_lookup(request.user, values["unit"], hidden_matches)
            response_data = {
                "message": "A possible match exists in another unit",
                "requires_exact_lookup": True,
                "lookup_token": token,
            }
            if visible_matches:
                response_data["visible_matches"] = [
                    self._duplicate_summary(student) for student in visible_matches
                ]
            return Response(response_data, status=status.HTTP_409_CONFLICT)
        if visible_matches and not confirm_duplicate:
            return Response(
                {
                    "message": (
                        "A possible duplicate exists. Review the visible match or "
                        "confirm a new registration."
                    ),
                    "requires_confirmation": True,
                    "matches": [
                        self._duplicate_summary(student) for student in visible_matches
                    ],
                },
                status=status.HTTP_409_CONFLICT,
            )

        student, enrollment = register_student(values=values, actor=request.user)
        response_data = StudentSerializer(
            student, context=self.get_serializer_context()
        ).data
        response_data["enrollment_id"] = str(enrollment.pk)
        return Response(response_data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _duplicate_summary(student):
        return {
            "id": str(student.pk),
            "name": f"{student.first_name} {student.last_name}",
            "home_unit": student.home_unit.code,
            "registration_number": student.registration_number,
        }

    @extend_schema(
        request=StudentDuplicateLookupSerializer,
        responses={status.HTTP_200_OK: StudentDuplicateLookupResultSerializer},
    )
    @action(detail=False, methods=("post",), url_path="duplicate-lookup")
    def duplicate_lookup(self, request):
        serializer = StudentDuplicateLookupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        matches = lookup_student_duplicate(
            actor=request.user,
            token=values["token"],
            phone=values.get("phone"),
            registration_number=values.get("registration_number"),
        )
        return Response({"matches": matches})

    @extend_schema(
        request=StudentImportSerializer, responses=StudentImportResultSerializer
    )
    @action(
        detail=False,
        methods=("post",),
        url_path="import",
        parser_classes=(MultiPartParser, FormParser),
    )
    def import_students(self, request):
        serializer = StudentImportSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(import_student_csv(serializer.validated_data["file"], request))

    @extend_schema(
        request=EnrollStudentInUnitSerializer,
        responses={status.HTTP_201_CREATED: EnrollStudentInUnitResultSerializer},
    )
    @action(detail=False, methods=("post",), url_path="enroll-in-unit")
    def enroll_in_unit(self, request):
        serializer = EnrollStudentInUnitSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        student = None
        if values.get("student"):
            student = (
                Student.objects.for_user(request.user)
                .filter(pk=values["student"])
                .first()
            )
            if student is None:
                raise PermissionDenied("You may not access this student.")
        enrollment = enroll_student_in_unit(
            actor=request.user,
            class_group=values["class_group"],
            student=student,
            enrollment_token=values.get("enrollment_token"),
        )
        return Response(
            {
                "id": str(enrollment.pk),
                "student": str(enrollment.student_id),
                "unit": str(enrollment.unit_id),
                "course": str(enrollment.course_id),
                "class_group": str(enrollment.class_group_id),
                "status": enrollment.status,
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=StudentTransferSerializer, responses=StudentSerializer)
    @action(detail=True, methods=("post",))
    def transfer(self, request, pk=None):
        student = self.get_queryset().filter(pk=pk).first()
        if student is None:
            from rest_framework.exceptions import NotFound

            raise NotFound()
        self.check_object_permissions(request, student)
        serializer = StudentTransferSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = transfer_student(
            student=student,
            target_unit=serializer.validated_data["home_unit"],
            actor=request.user,
        )
        return Response(
            StudentSerializer(student, context=self.get_serializer_context()).data
        )

    @extend_schema(request=StudentStatusSerializer, responses=StudentSerializer)
    @action(detail=True, methods=("post",), url_path="change-status")
    def change_status(self, request, pk=None):
        student = self.get_object()
        serializer = StudentStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = change_student_status(
            student=student,
            status=serializer.validated_data["status"],
            reason=serializer.validated_data["reason"],
            actor=request.user,
        )
        return Response(
            StudentSerializer(student, context=self.get_serializer_context()).data
        )

    @extend_schema(request=InviteStudentSerializer, responses=StudentSerializer)
    @action(detail=True, methods=("post",), url_path="invite")
    def invite(self, request, pk=None):
        student = self.get_object()
        serializer = InviteStudentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        student = invite_student(
            student,
            request.user,
            request,
            email=serializer.validated_data.get("email"),
        )
        return Response(
            StudentSerializer(student, context=self.get_serializer_context()).data
        )


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
        user = self.request.user
        has_management_scope = (
            user.has_role_global(
                Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.AUDITOR
            )
            or bool(user.unit_ids_for(Role.UNIT_MANAGER))
            or bool(user.department_ids_for_hod())
        )
        if user.has_role(Role.STUDENT) and not has_management_scope:
            return queryset.filter(is_active=True)
        return queryset

    def perform_create(self, serializer):
        student = serializer.validated_data["student"]
        if not may_manage_student(self.request.user, student):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You may only manage guardians for students in your assigned scope."
            )
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
        if not may_manage_student(self.request.user, student):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied(
                "You may only manage guardians for students in your assigned scope."
            )
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
