from django.conf import settings
from django.db import models

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class ApplicationQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(department__role_scopes__user=user).distinct()
        return self.none()


class EnrollmentQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(course__department__role_scopes__user=user).distinct()
        if user.role == Role.STUDENT:
            return self.filter(student__user=user)
        if user.role == Role.TEACHER:
            return self.filter(course__created_by=user)
        return self.none()


class CourseAccessQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(course__department__role_scopes__user=user).distinct()
        if user.role == Role.STUDENT:
            return self.filter(student__user=user, is_active=True)
        if user.role == Role.TEACHER:
            return self.filter(course__created_by=user, is_active=True)
        return self.none()


class Application(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    department = models.ForeignKey(
        "org.Department", on_delete=models.PROTECT, related_name="applications"
    )
    program = models.ForeignKey(
        "org.Program",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="applications",
    )
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="applications"
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    statement = models.TextField(blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    student = models.OneToOneField(
        "people.Student",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="application",
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_applications",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    objects = ApplicationQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return f"{self.first_name} {self.last_name} — {self.course}"


class Enrollment(BaseModel):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="enrollments"
    )
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="enrollments"
    )
    application = models.OneToOneField(
        Application,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="enrollment",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PENDING
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_enrollments",
    )
    activated_at = models.DateTimeField(null=True, blank=True)

    objects = EnrollmentQuerySet.as_manager()

    class Meta:
        ordering = ("-created_at",)
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("student", "course"), name="unique_student_course_enrollment"
            )
        ]


class CourseAccess(BaseModel):
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="course_access"
    )
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="student_access"
    )
    enrollment = models.OneToOneField(
        Enrollment, on_delete=models.PROTECT, related_name="access_projection"
    )
    is_active = models.BooleanField(default=True)

    objects = CourseAccessQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("student", "course"), name="unique_student_course_access"
            )
        ]
