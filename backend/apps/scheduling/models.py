from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet, UnitScopedQuerySet


class RoomQuerySet(ScopedQuerySet):
    unit_field = "department__unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(department_id__in=department_ids)
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(department__unit_id__in=manager_unit_ids)
        teacher_unit_ids = user.unit_ids_for(Role.TEACHER)
        if teacher_unit_ids:
            scope |= Q(department__unit_id__in=teacher_unit_ids, is_active=True)
        if user.has_role(Role.STUDENT):
            class_ids = ClassGroup.objects.for_user(user).filter(is_active=True)
            scope |= Q(
                timetable_slots__class_group__in=class_ids,
                timetable_slots__is_active=True,
                is_active=True,
            )
        return self.filter(scope).distinct()


class ClassGroupQuerySet(ScopedQuerySet):
    unit_field = "course__unit"

    def for_user(self, user):
        from apps.enrollment.models import CourseAccess

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
                teacher_assignments__teacher=user,
                teacher_assignments__is_active=True,
            )
        if user.has_role(Role.STUDENT):
            active_courses = CourseAccess.objects.for_user(user).filter(is_active=True)
            scope |= Q(
                course_id__in=active_courses.values("course_id"),
                is_active=True,
                status__in=(
                    ClassGroup.Status.PLANNED,
                    ClassGroup.Status.OPEN,
                    ClassGroup.Status.RUNNING,
                ),
            )
        return self.filter(scope).distinct()


class ClassTeacherQuerySet(UnitScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(unit_id__in=unit_ids)
        if user.has_role(Role.TEACHER):
            scope |= Q(teacher=user, is_active=True)
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(class_group__course__department_id__in=department_ids)
        return self.filter(scope).distinct()


class TimetableSlotQuerySet(UnitScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        group_ids = ClassGroup.objects.for_user(user).values("id")
        return self.filter(
            class_group_id__in=group_ids,
            class_group__status__in=(
                ClassGroup.Status.PLANNED,
                ClassGroup.Status.OPEN,
                ClassGroup.Status.RUNNING,
            ),
        )


class Room(BaseModel):
    department = models.ForeignKey(
        "org.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="rooms",
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=32, unique=True)
    capacity = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    objects = RoomQuerySet.as_manager()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return f"{self.name} ({self.code})"


class ClassGroup(BaseModel):
    class Status(models.TextChoices):
        PLANNED = "PLANNED", "Planned"
        OPEN = "OPEN", "Open"
        RUNNING = "RUNNING", "Running"
        COMPLETED = "COMPLETED", "Completed"
        CANCELLED = "CANCELLED", "Cancelled"

    ALLOWED_STATUS_TRANSITIONS: ClassVar[dict[str, set[str]]] = {
        Status.PLANNED: {Status.OPEN, Status.CANCELLED},
        Status.OPEN: {Status.RUNNING, Status.CANCELLED},
        Status.RUNNING: {Status.COMPLETED, Status.CANCELLED},
        Status.COMPLETED: set(),
        Status.CANCELLED: set(),
    }

    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="class_groups"
    )
    academic_period = models.ForeignKey(
        "org.AcademicPeriod",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="class_groups",
    )
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=40, unique=True)
    capacity = models.PositiveIntegerField(default=40)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.PLANNED
    )
    is_active = models.BooleanField(default=True)

    objects = ClassGroupQuerySet.as_manager()

    class Meta:
        ordering = ("course__title", "name")
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=models.Q(capacity__gt=0),
                name="class_group_capacity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    status__in=("PLANNED", "OPEN", "RUNNING", "COMPLETED", "CANCELLED")
                ),
                name="class_group_status_valid",
            ),
        ]

    def clean(self):
        if self.capacity < 1:
            raise ValidationError({"capacity": "Capacity must be at least one."})
        if (
            self.academic_period_id
            and self.course_id
            and self.academic_period.unit_id
            and self.academic_period.unit_id != self.course.unit_id
        ):
            raise ValidationError(
                {"academic_period": "The academic period belongs to another unit."}
            )
        if self.pk and not self._state.adding:
            previous = type(self).objects.filter(pk=self.pk).values("status").first()
            if previous and previous["status"] != self.status:
                if (
                    self.status
                    not in self.ALLOWED_STATUS_TRANSITIONS[previous["status"]]
                ):
                    raise ValidationError(
                        {"status": "This class status transition is not allowed."}
                    )
                if (
                    self.status == self.Status.RUNNING
                    and not self.teacher_assignments.filter(is_active=True).exists()
                ):
                    raise ValidationError(
                        {
                            "status": "Assign at least one active teacher before starting."
                        }
                    )
        if (
            not self._state.adding
            and self.pk
            and self.course_id
            and self.timetable_slots.exclude(unit_id=self.course.unit_id).exists()
        ):
            raise ValidationError(
                {"course": "The course change conflicts with existing timetable slots."}
            )
        if (
            not self._state.adding
            and self.pk
            and self.course_id
            and self.teacher_assignments.exclude(unit_id=self.course.unit_id).exists()
        ):
            raise ValidationError(
                {"course": "The course change conflicts with teacher assignments."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def has_teacher(self, user):
        return self.teacher_assignments.filter(teacher=user, is_active=True).exists()

    def __str__(self):
        return f"{self.course.code} — {self.name}"


class ClassTeacher(BaseModel):
    class Role(models.TextChoices):
        LEAD = "LEAD", "Lead teacher"
        ASSISTANT = "ASSISTANT", "Assistant teacher"

    unit = models.ForeignKey(
        "org.BusinessUnit",
        on_delete=models.PROTECT,
        related_name="class_teacher_assignments",
    )
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, related_name="teacher_assignments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="class_teacher_assignments",
    )
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.ASSISTANT)
    is_active = models.BooleanField(default=True)

    objects = ClassTeacherQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("class_group", "teacher"),
                name="unique_class_teacher_assignment",
            ),
            models.UniqueConstraint(
                fields=("class_group",),
                condition=models.Q(role="LEAD", is_active=True),
                name="unique_active_class_lead_teacher",
            ),
        ]

    def clean(self):
        if (
            self.class_group_id
            and self.unit_id
            and self.class_group.course.unit_id != self.unit_id
        ):
            raise ValidationError(
                {"unit": "The assignment must use the class's course unit."}
            )

    def save(self, *args, **kwargs):
        if self.unit_id is None and self.class_group_id:
            self.unit_id = self.class_group.course.unit_id
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(set(kwargs["update_fields"]) | {"unit"})
        self.clean()
        super().save(*args, **kwargs)


class TimetableSlot(BaseModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

    unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="timetable_slots"
    )
    class_group = models.ForeignKey(
        ClassGroup, on_delete=models.CASCADE, related_name="timetable_slots"
    )
    room = models.ForeignKey(
        Room,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="timetable_slots",
    )
    weekday = models.PositiveSmallIntegerField(choices=Weekday.choices)
    starts_at = models.TimeField()
    ends_at = models.TimeField()
    effective_from = models.DateField()
    effective_until = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    objects = TimetableSlotQuerySet.as_manager()

    class Meta:
        ordering = ("weekday", "starts_at")
        indexes = [  # noqa: RUF012
            models.Index(
                fields=("weekday", "starts_at", "ends_at"),
                name="timetable_weekday_time_idx",
            )
        ]

    def clean(self):
        if (
            self.class_group_id
            and self.unit_id
            and self.class_group.course.unit_id != self.unit_id
        ):
            raise ValidationError(
                {"unit": "The timetable slot must use its course's unit."}
            )

    def save(self, *args, **kwargs):
        derived_unit = self.unit_id is None
        if derived_unit and self.class_group_id:
            self.unit_id = self.class_group.course.unit_id
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(set(kwargs["update_fields"]) | {"unit"})
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.class_group} — {self.get_weekday_display()} {self.starts_at}"
