from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class StudentQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(department__role_scopes__user=user).distinct()
        if user.role == Role.STUDENT:
            return self.filter(user=user)
        return self.none()


class StaffProfileQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(department__role_scopes__user=user).distinct()
        return self.none()


class GuardianQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(student__department__role_scopes__user=user).distinct()
        if user.role == Role.STUDENT:
            return self.filter(student__user=user)
        return self.none()


class Student(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="student_profile",
    )
    department = models.ForeignKey(
        "org.Department", on_delete=models.PROTECT, related_name="students"
    )
    program = models.ForeignKey(
        "org.Program",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="students",
    )
    registration_number = models.CharField(max_length=64, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField()
    phone = models.CharField(max_length=32, blank=True)
    admission_year = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)

    objects = StudentQuerySet.as_manager()

    class Meta:
        ordering = ("registration_number",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(admission_year__gte=2000),
                name="student_admission_year_valid",
            )
        ]

    def __str__(self):
        return f"{self.registration_number} — {self.first_name} {self.last_name}"


class StaffProfile(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff_profile"
    )
    department = models.ForeignKey(
        "org.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="staff_profiles",
    )
    job_title = models.CharField(max_length=160, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("user__display_name", "user__email")

    objects = StaffProfileQuerySet.as_manager()

    def __str__(self):
        return self.user.display_name or self.user.email


class Guardian(BaseModel):
    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="guardians"
    )
    full_name = models.CharField(max_length=200)
    relationship = models.CharField(max_length=80)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("full_name",)

    objects = GuardianQuerySet.as_manager()

    def __str__(self):
        return self.full_name


class RegistrationSequence(models.Model):
    department = models.ForeignKey(
        "org.Department",
        on_delete=models.CASCADE,
        related_name="registration_sequences",
    )
    year = models.PositiveSmallIntegerField()
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("department", "year"),
                name="unique_registration_sequence_department_year",
            )
        ]


def allocate_registration_number(department, year):
    from django.db import transaction

    with transaction.atomic():
        RegistrationSequence.objects.get_or_create(department=department, year=year)
        sequence = RegistrationSequence.objects.select_for_update().get(
            department=department, year=year
        )
        value = sequence.next_value
        sequence.next_value += 1
        sequence.save(update_fields=("next_value",))
        return f"{department.code}-{year}-{value:04d}"
