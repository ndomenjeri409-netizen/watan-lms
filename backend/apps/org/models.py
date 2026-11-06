from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet, UnitScopedQuerySet


class BusinessUnit(BaseModel):
    class Kind(models.TextChoices):
        ACADEMIC = "ACADEMIC"
        TRAINING = "TRAINING"
        DRIVING = "DRIVING"
        SERVICES = "SERVICES"
        GROUP = "GROUP"

    code = models.CharField(max_length=8, unique=True)
    name = models.CharField(max_length=160)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    currency = models.CharField(max_length=3, default="KES")
    modules = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("code",)

    def __str__(self):
        return f"{self.code} — {self.name}"


class CampusQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(departments__role_scopes__user=user).distinct()
        return self.none()


class Campus(BaseModel):
    name = models.CharField(max_length=160, unique=True)
    code = models.CharField(max_length=32, unique=True)
    is_active = models.BooleanField(default=True)

    objects = CampusQuerySet.as_manager()

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class DepartmentQuerySet(UnitScopedQuerySet):
    def for_user(self, user):
        queryset = super().for_user(user)
        if not user.is_authenticated:
            return queryset
        if user.has_role(Role.HOD) and not user.has_global_read():
            return queryset.filter(role_scopes__user=user).distinct()
        return queryset


class Department(BaseModel):
    unit = models.ForeignKey(
        BusinessUnit,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="departments",
    )
    campus = models.ForeignKey(
        Campus,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="departments",
    )
    name = models.CharField(max_length=160)
    code = models.CharField(
        max_length=8,
        unique=True,
        validators=[RegexValidator(r"^[A-Z0-9]{2,8}$")],
    )
    is_active = models.BooleanField(default=True)
    archived_at = models.DateTimeField(null=True, blank=True)

    objects = DepartmentQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(Lower("code"), name="unique_department_code_ci"),
            models.UniqueConstraint(Lower("name"), name="unique_department_name_ci"),
        ]
        ordering = ("name",)

    def __str__(self):
        return self.name


class ProgramQuerySet(ScopedQuerySet):
    def for_user(self, user):
        return (
            Program.objects.none()
            if not user.is_authenticated
            else self.filter(department__in=Department.objects.for_user(user))
        )


class Program(BaseModel):
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="programs"
    )
    name = models.CharField(max_length=160)
    code = models.CharField(max_length=32, unique=True)
    is_active = models.BooleanField(default=True)

    objects = ProgramQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("department", "name"), name="unique_program_name_per_department"
            )
        ]
        ordering = ("name",)

    def __str__(self):
        return self.name


class AcademicPeriodQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.HOD}:
            return self
        return self.none()


class AcademicPeriod(BaseModel):
    name = models.CharField(max_length=100, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_current = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = AcademicPeriodQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(ends_on__gte=models.F("starts_on")),
                name="academic_period_end_after_start",
            )
        ]
        ordering = ("-starts_on",)

    def __str__(self):
        return self.name
