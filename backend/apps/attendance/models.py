from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class AttendanceSessionQuerySet(ScopedQuerySet):
    def for_user(self, user):
        from apps.enrollment.models import CourseAccess

        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(class_group__course__department_id__in=department_ids)
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(class_group__course__unit_id__in=unit_ids)
        if user.has_role(Role.TEACHER):
            scope |= Q(
                class_group__teacher_assignments__teacher=user,
                class_group__teacher_assignments__is_active=True,
            )
        if user.has_role(Role.STUDENT):
            active_courses = CourseAccess.objects.for_user(user).filter(is_active=True)
            scope |= Q(
                class_group__course_id__in=active_courses.values("course_id"),
                is_open=True,
            )
        return self.filter(scope).distinct()


class AttendanceRecordQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(session__class_group__course__department_id__in=department_ids)
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(session__class_group__course__unit_id__in=unit_ids)
        if user.has_role(Role.TEACHER):
            scope |= Q(
                session__class_group__teacher_assignments__teacher=user,
                session__class_group__teacher_assignments__is_active=True,
            )
        if user.has_role(Role.STUDENT):
            scope |= Q(student__user=user)
        return self.filter(scope).distinct()


class AttendanceSession(BaseModel):
    class_group = models.ForeignKey(
        "scheduling.ClassGroup",
        on_delete=models.PROTECT,
        related_name="attendance_sessions",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opened_attendance_sessions",
    )
    title = models.CharField(max_length=160, blank=True)
    is_open = models.BooleanField(default=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    objects = AttendanceSessionQuerySet.as_manager()

    class Meta:
        ordering = ("-opened_at",)
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("class_group",),
                condition=models.Q(is_open=True),
                name="unique_open_attendance_session_per_group",
            )
        ]


class QrToken(BaseModel):
    session = models.ForeignKey(
        AttendanceSession, on_delete=models.CASCADE, related_name="qr_tokens"
    )
    token_digest = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [  # noqa: RUF012
            models.Index(
                fields=("session", "expires_at"), name="qr_token_session_exp_idx"
            )
        ]


class AttendanceRecord(BaseModel):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        ABSENT = "ABSENT", "Absent"
        LATE = "LATE", "Late"
        EXCUSED = "EXCUSED", "Excused"

    session = models.ForeignKey(
        AttendanceSession, on_delete=models.PROTECT, related_name="records"
    )
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="attendance_records"
    )
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.PRESENT
    )
    checked_in_at = models.DateTimeField(auto_now_add=True)

    objects = AttendanceRecordQuerySet.as_manager()

    class Meta:
        ordering = ("checked_in_at",)
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("session", "student"),
                name="unique_attendance_record_session_student",
            )
        ]


class CheckIn(BaseModel):
    record = models.OneToOneField(
        AttendanceRecord, on_delete=models.PROTECT, related_name="check_in"
    )
    qr_token = models.ForeignKey(
        QrToken, on_delete=models.PROTECT, related_name="check_ins"
    )
    client_checkin_id = models.UUIDField(null=True, blank=True, unique=True)
