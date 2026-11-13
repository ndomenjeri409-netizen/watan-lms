from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
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
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(departments__id__in=department_ids)
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(departments__unit_id__in=manager_unit_ids)
        return self.filter(scope).distinct()


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
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_global_read():
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(pk__in=department_ids)
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(unit_id__in=manager_unit_ids)
        return self.filter(scope).distinct()


class Department(BaseModel):
    unit = models.ForeignKey(
        BusinessUnit,
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

    def clean(self):
        if self._state.adding or not self.pk:
            return
        previous_unit_id = (
            Department.objects.filter(pk=self.pk)
            .values_list("unit_id", flat=True)
            .first()
        )
        if previous_unit_id != self.unit_id and (
            self.programs.exists() or self.courses.exists()
        ):
            raise ValidationError(
                {"unit": "A department with programs or courses cannot change units."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProgramQuerySet(UnitScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_global_read():
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(department_id__in=department_ids)
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(unit_id__in=manager_unit_ids)
        return self.filter(scope).distinct()


class Program(BaseModel):
    unit = models.ForeignKey(
        BusinessUnit, on_delete=models.PROTECT, related_name="programs"
    )
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

    def clean(self):
        if (
            self.department_id
            and self.unit_id
            and self.department.unit_id != self.unit_id
        ):
            raise ValidationError(
                {"unit": "The program must use its department's unit."}
            )
        if (
            not self._state.adding
            and self.pk
            and self.courses.exclude(
                department_id=self.department_id, unit_id=self.unit_id
            ).exists()
        ):
            raise ValidationError(
                {
                    "department": "A program with courses cannot change departments or units."
                }
            )

    def save(self, *args, **kwargs):
        derived_unit = self.unit_id is None
        if derived_unit and self.department_id:
            self.unit_id = self.department.unit_id
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(set(kwargs["update_fields"]) | {"unit"})
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class AcademicPeriodQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self
        if not user.has_role(Role.HOD, Role.UNIT_MANAGER):
            return self.none()

        unit_ids = user.unit_ids_for(Role.HOD, Role.UNIT_MANAGER)
        return self.filter(Q(unit__isnull=True) | Q(unit_id__in=unit_ids)).distinct()


class AcademicPeriod(BaseModel):
    class Kind(models.TextChoices):
        TERM = "TERM", "Term"
        INTAKE = "INTAKE", "Intake"

    name = models.CharField(max_length=100, unique=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    kind = models.CharField(max_length=8, choices=Kind.choices, null=True, blank=True)
    unit = models.ForeignKey(
        BusinessUnit,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="academic_periods",
    )
    is_current = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = AcademicPeriodQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(ends_on__gte=models.F("starts_on")),
                name="academic_period_end_after_start",
            ),
            models.CheckConstraint(
                condition=Q(kind__isnull=True) | Q(kind__in=("TERM", "INTAKE")),
                name="academic_period_kind_valid",
            ),
        ]
        ordering = ("-starts_on",)

    def clean(self):
        if (
            self.pk
            and self.unit_id
            and self.class_groups.exclude(course__unit_id=self.unit_id).exists()
        ):
            raise ValidationError(
                {"unit": "The period's unit cannot conflict with its existing classes."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
