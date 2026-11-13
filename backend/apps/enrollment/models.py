from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet, UnitScopedQuerySet


class ApplicationQuerySet(ScopedQuerySet):
    unit_field = "course__unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        if user.has_role(Role.HOD):
            department_ids = user.department_ids_for_hod()
            if department_ids:
                scope |= Q(department_id__in=department_ids)
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(course__unit_id__in=unit_ids)
        return self.filter(scope).distinct()


class EnrollmentQuerySet(UnitScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(course__department_id__in=department_ids)
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(unit_id__in=unit_ids)
        if user.has_role(Role.TEACHER):
            scope |= Q(
                course__teacher_assignments__teacher=user,
                course__teacher_assignments__can_edit_content=True,
                course__teacher_assignments__is_active=True,
            )
        if user.has_role(Role.STUDENT):
            scope |= Q(student__user=user)
        return self.filter(scope).distinct()


class CourseAccessQuerySet(ScopedQuerySet):
    unit_field = "course__unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(course__department_id__in=department_ids)
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(course__unit_id__in=unit_ids)
        if user.has_role(Role.TEACHER):
            scope |= Q(
                course__teacher_assignments__teacher=user,
                course__teacher_assignments__can_edit_content=True,
                course__teacher_assignments__is_active=True,
                is_active=True,
            )
        if user.has_role(Role.STUDENT):
            scope |= Q(student__user=user, is_active=True)
        return self.filter(scope).distinct()


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
    email = models.EmailField(blank=True)
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

    unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="enrollments"
    )
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="enrollments"
    )
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="enrollments"
    )
    class_group = models.ForeignKey(
        "scheduling.ClassGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="enrollments",
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
            ),
            models.CheckConstraint(
                condition=~Q(status="ACTIVE") | Q(class_group__isnull=False),
                name="active_enrollment_requires_class",
            ),
        ]

    def clean(self):
        if self.course_id and self.unit_id and self.course.unit_id != self.unit_id:
            raise ValidationError(
                {"unit": "The enrollment must use its course's unit."}
            )
        if self.class_group_id and self.course_id:
            if self.class_group.course_id != self.course_id:
                raise ValidationError(
                    {"class_group": "The class must use the enrollment's course."}
                )
            if self.class_group.course.unit_id != self.unit_id:
                raise ValidationError(
                    {
                        "class_group": "The class must use the enrollment's business unit."
                    }
                )
        if self.status == self.Status.ACTIVE and not self.class_group_id:
            raise ValidationError(
                {"class_group": "Assign the enrollment to a class before activation."}
            )

    def save(self, *args, **kwargs):
        derived_unit = self.unit_id is None
        if derived_unit and self.course_id:
            self.unit_id = self.course.unit_id
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(set(kwargs["update_fields"]) | {"unit"})
        self.clean()
        super().save(*args, **kwargs)


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
