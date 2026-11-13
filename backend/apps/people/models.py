import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class StudentQuerySet(ScopedQuerySet):
    def update(self, **kwargs):
        if {"home_unit", "home_unit_id", "registration_number"}.intersection(kwargs):
            raise ValidationError(
                "A student's registration number and home unit may only change through the audited transfer flow."
            )
        return super().update(**kwargs)

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER, Role.BURSAR, Role.CASHIER)
        if unit_ids:
            scope |= (
                Q(home_unit_id__in=unit_ids)
                | Q(enrollments__unit_id__in=unit_ids)
                | Q(invoices__unit_id__in=unit_ids)
            )

        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(enrollments__course__department_id__in=department_ids)

        if user.has_role(Role.TEACHER):
            scope |= Q(
                enrollments__class_group__is_active=True,
                enrollments__class_group__teacher_assignments__teacher=user,
                enrollments__class_group__teacher_assignments__is_active=True,
            )

        if user.has_role(Role.STUDENT):
            scope |= Q(user=user)

        return self.filter(scope).distinct()


class StaffProfileQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if unit_ids:
            scope |= Q(department__unit_id__in=unit_ids)
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(department_id__in=department_ids)
        return self.filter(scope).distinct()


class GuardianQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self
        unit_ids = user.unit_ids_for(Role.UNIT_MANAGER, Role.BURSAR)
        if not unit_ids:
            return self.none()
        return self.filter(
            Q(student__home_unit_id__in=unit_ids)
            | Q(student__enrollments__unit_id__in=unit_ids)
            | Q(student__invoices__unit_id__in=unit_ids)
        ).distinct()


class Student(BaseModel):
    class Status(models.TextChoices):
        APPLICANT = "APPLICANT", "Applicant"
        ACTIVE = "ACTIVE", "Active"
        COMPLETED = "COMPLETED", "Completed"
        WITHDRAWN = "WITHDRAWN", "Withdrawn"
        SUSPENDED = "SUSPENDED", "Suspended"
        DEFERRED = "DEFERRED", "Deferred"

    class AccountStatus(models.TextChoices):
        NONE = "NONE", "None"
        INVITED = "INVITED", "Invited"
        ACTIVE = "ACTIVE", "Active"

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
    home_unit = models.ForeignKey(
        "org.BusinessUnit",
        on_delete=models.PROTECT,
        related_name="home_students",
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
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=32)
    date_of_birth = models.DateField(null=True, blank=True)
    national_id = models.CharField(max_length=32, blank=True)
    photo_file = models.ForeignKey(
        "files.StoredFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="student_profiles",
    )
    admission_year = models.PositiveSmallIntegerField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE
    )
    is_active = models.BooleanField(default=True)
    account_status = models.CharField(
        max_length=8,
        choices=AccountStatus.choices,
        default=AccountStatus.NONE,
    )

    objects = StudentQuerySet.as_manager()

    class Meta:
        ordering = ("registration_number",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(admission_year__gte=2000),
                name="student_admission_year_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(account_status="NONE", user__isnull=True)
                    | (
                        Q(account_status__in=("INVITED", "ACTIVE"))
                        & Q(user__isnull=False)
                    )
                ),
                name="student_account_status_consistent",
            ),
        ]

    def save(self, *args, **kwargs):
        if self.user_id and self.account_status == self.AccountStatus.NONE:
            self.account_status = self.AccountStatus.ACTIVE
        is_new = self._state.adding
        if is_new and not self.home_unit_id:
            parsed = parse_registration_number(self.registration_number)
            if parsed and parsed["unit_code"]:
                from apps.org.models import BusinessUnit

                self.home_unit = BusinessUnit.objects.filter(
                    code__iexact=parsed["unit_code"]
                ).first()
                if self.home_unit is None:
                    raise ValidationError(
                        {
                            "home_unit": (
                                "The registration number prefix does not match a business unit."
                            )
                        }
                    )
            elif self.department_id:
                self.home_unit = self.department.unit
        if is_new and self.home_unit_id:
            parsed = parse_registration_number(self.registration_number)
            if (
                parsed
                and parsed["unit_code"]
                and self.home_unit.code.upper() != parsed["unit_code"]
            ):
                raise ValidationError(
                    {
                        "home_unit": (
                            "The home unit must match the registration number prefix."
                        )
                    }
                )
        if self.pk:
            previous = (
                type(self)
                .objects.filter(pk=self.pk)
                .values("registration_number", "home_unit_id")
                .first()
            )
            if (
                previous is not None
                and previous["registration_number"] != self.registration_number
            ):
                raise ValidationError(
                    {
                        "registration_number": "A student's registration number is immutable."
                    }
                )
            if (
                previous is not None
                and previous["home_unit_id"] != self.home_unit_id
                and not getattr(self, "_allow_home_unit_transfer", False)
            ):
                raise ValidationError(
                    {
                        "home_unit": (
                            "A student's home unit may only change through the audited transfer flow."
                        )
                    }
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.registration_number} — {self.first_name} {self.last_name}"


class StudentDuplicateLookup(BaseModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_duplicate_lookups",
    )
    unit = models.ForeignKey(
        "org.BusinessUnit",
        on_delete=models.CASCADE,
        related_name="student_duplicate_lookups",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    candidates = models.ManyToManyField(
        Student,
        through="StudentDuplicateCandidate",
        related_name="duplicate_lookups",
    )

    def is_valid(self, actor, unit):
        return (
            self.actor_id == actor.pk
            and self.unit_id == unit.pk
            and self.used_at is None
            and self.expires_at > timezone.now()
        )


class StudentDuplicateCandidate(models.Model):
    lookup = models.ForeignKey(
        StudentDuplicateLookup,
        on_delete=models.CASCADE,
        related_name="candidate_links",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="duplicate_candidate_links",
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("lookup", "student"),
                name="unique_student_duplicate_candidate",
            )
        ]


class StudentEnrollmentGrant(BaseModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="student_enrollment_grants",
    )
    unit = models.ForeignKey(
        "org.BusinessUnit",
        on_delete=models.CASCADE,
        related_name="student_enrollment_grants",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="enrollment_grants",
    )
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)


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
    unit = models.ForeignKey(
        "org.BusinessUnit",
        on_delete=models.PROTECT,
        related_name="registration_sequences",
    )
    department = models.ForeignKey(
        "org.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="registration_sequences",
    )
    year = models.PositiveSmallIntegerField()
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("unit", "department", "year"),
                condition=Q(department__isnull=False),
                name="uniq_regseq_dept",
            ),
            models.UniqueConstraint(
                fields=("unit", "year"),
                condition=Q(department__isnull=True),
                name="uniq_regseq_unit",
            ),
        ]

    def clean(self):
        if (
            self.department_id
            and self.unit_id
            and self.department.unit_id != self.unit_id
        ):
            raise ValidationError(
                {"unit": "The sequence unit must match the department's unit."}
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


_REGISTRATION_NUMBER_PATTERNS = (
    re.compile(
        r"^(?P<unit>[A-Z0-9]{2,8})/(?P<department>[A-Z0-9]{2,8})/"
        r"(?P<year>\d{4})/(?P<sequence>\d{4,})$"
    ),
    re.compile(r"^(?P<unit>[A-Z0-9]{2,8})/(?P<year>\d{4})/(?P<sequence>\d{4,})$"),
    re.compile(r"^(?P<department>[A-Z0-9]{2,8})-(?P<year>\d{4})-(?P<sequence>\d{4,})$"),
)


def parse_registration_number(value):
    for pattern in _REGISTRATION_NUMBER_PATTERNS:
        match = pattern.fullmatch(value.upper())
        if match:
            parts = match.groupdict()
            return {
                "unit_code": parts.get("unit"),
                "department_code": parts.get("department"),
                "year": int(parts["year"]),
                "sequence": int(parts["sequence"]),
            }
    return None


def format_registration_number(unit, department, year, sequence):
    if sequence < 1:
        raise ValueError("Registration sequence must be positive.")
    if department and department.unit_id != unit.id:
        raise ValidationError(
            {"department": "The department must belong to the registration unit."}
        )
    prefix = unit.code.upper()
    if department:
        prefix = f"{prefix}/{department.code.upper()}"
    return f"{prefix}/{year}/{sequence:04d}"


def allocate_registration_number(unit, year, department=None):
    from django.db import transaction

    if department and department.unit_id != unit.id:
        raise ValidationError(
            {"department": "The department must belong to the registration unit."}
        )
    scope = {"unit": unit, "department": department, "year": year}
    with transaction.atomic():
        RegistrationSequence.objects.get_or_create(**scope)
        sequence = RegistrationSequence.objects.select_for_update().get(**scope)
        value = sequence.next_number
        sequence.next_number += 1
        sequence.save(update_fields=("next_number",))
        return format_registration_number(unit, department, year, value)
