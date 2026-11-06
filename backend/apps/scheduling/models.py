from django.conf import settings
from django.db import models

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class RoomQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(department__role_scopes__user=user).distinct()
        if user.role == Role.TEACHER:
            return self.filter(is_active=True)
        if user.role == Role.STUDENT:
            return self.filter(is_active=True)
        return self.none()


class ClassGroupQuerySet(ScopedQuerySet):
    def for_user(self, user):
        from apps.enrollment.models import CourseAccess

        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(course__department__role_scopes__user=user).distinct()
        if user.role == Role.TEACHER:
            return self.filter(teacher=user)
        if user.role == Role.STUDENT:
            return self.filter(
                course_id__in=CourseAccess.objects.for_user(user).values("course_id"),
                is_active=True,
            )
        return self.none()


class TimetableSlotQuerySet(ScopedQuerySet):
    def for_user(self, user):
        group_ids = ClassGroup.objects.for_user(user).values("id")
        return self.filter(class_group_id__in=group_ids)


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
    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="class_groups"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="teaching_groups",
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
    is_active = models.BooleanField(default=True)

    objects = ClassGroupQuerySet.as_manager()

    class Meta:
        ordering = ("course__title", "name")

    def __str__(self):
        return f"{self.course.code} — {self.name}"


class TimetableSlot(BaseModel):
    class Weekday(models.IntegerChoices):
        MONDAY = 0, "Monday"
        TUESDAY = 1, "Tuesday"
        WEDNESDAY = 2, "Wednesday"
        THURSDAY = 3, "Thursday"
        FRIDAY = 4, "Friday"
        SATURDAY = 5, "Saturday"
        SUNDAY = 6, "Sunday"

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

    def __str__(self):
        return f"{self.class_group} — {self.get_weekday_display()} {self.starts_at}"
