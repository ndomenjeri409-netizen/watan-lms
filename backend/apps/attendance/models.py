from django.conf import settings
from django.db import models

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class AttendanceSessionQuerySet(ScopedQuerySet):
    def for_user(self, user):
        from apps.enrollment.models import CourseAccess

        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(
                class_group__course__department__role_scopes__user=user
            ).distinct()
        if user.role == Role.TEACHER:
            return self.filter(class_group__teacher=user)
        if user.role == Role.STUDENT:
            return self.filter(
                class_group__course_id__in=CourseAccess.objects.for_user(user).values(
                    "course_id"
                ),
                is_open=True,
            )
        return self.none()


class AttendanceRecordQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(
                session__class_group__course__department__role_scopes__user=user
            ).distinct()
        if user.role == Role.TEACHER:
            return self.filter(session__class_group__teacher=user)
        if user.role == Role.STUDENT:
            return self.filter(student__user=user)
        return self.none()


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
        LATE = "LATE", "Late"

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
