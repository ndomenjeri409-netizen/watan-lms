from django.contrib.auth.models import (
    AbstractBaseUser,
    BaseUserManager,
    PermissionsMixin,
)
from django.db import models
from django.db.models import Q
from django.utils.functional import cached_property

from common.models import BaseModel

from .roles import GLOBAL_READ_ROLES, GLOBAL_ROLES, UNIT_SCOPED_ROLES, Role


class UserQuerySet(models.QuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.roles():
            return self.none()
        if user.has_role_global(Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR):
            return self

        scope = models.Q(pk=user.pk)
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= models.Q(role_scopes__department_id__in=department_ids)
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= models.Q(
                assignments__is_active=True,
                assignments__unit_id__in=manager_unit_ids,
            )
        return self.filter(scope).distinct()


class UserManager(BaseUserManager):
    def create_user(self, firebase_uid, email="", **extra):
        role = extra.pop("role", None)
        unit = extra.pop("unit", None)
        granted_by = extra.pop("granted_by", None)
        if role in UNIT_SCOPED_ROLES and unit is None:
            raise ValueError(f"{role} assignments require a business unit.")
        user = self.model(firebase_uid=firebase_uid, email=email, **extra)
        user.set_unusable_password()
        user.save(using=self._db)
        if role in GLOBAL_ROLES or (role == Role.BURSAR and unit is None):
            RoleAssignment.objects.using(self._db).get_or_create(
                user=user,
                role=role,
                unit=None,
                defaults={"is_active": True, "granted_by": granted_by},
            )
        elif role in UNIT_SCOPED_ROLES or role == Role.BURSAR:
            RoleAssignment.objects.using(self._db).get_or_create(
                user=user,
                role=role,
                unit=unit,
                defaults={"is_active": True, "granted_by": granted_by},
            )
        return user

    def create_superuser(self, firebase_uid, password=None, **extra):
        if not password:
            raise ValueError("A password is required for a superuser.")
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        user = self.model(firebase_uid=firebase_uid, **extra)
        user.set_password(password)
        user.save(using=self._db)
        RoleAssignment.objects.using(self._db).get_or_create(
            user=user,
            role=Role.SUPER_ADMIN,
            unit=None,
            defaults={"is_active": True},
        )
        return user


class User(BaseModel, AbstractBaseUser, PermissionsMixin):
    firebase_uid = models.CharField(max_length=128, unique=True)
    email = models.EmailField(blank=True)
    display_name = models.CharField(max_length=200, blank=True)
    phone_number = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    USERNAME_FIELD = "firebase_uid"
    objects = UserManager.from_queryset(UserQuerySet)()

    class Meta:
        ordering = ("email", "id")

    @cached_property
    def _active_role_assignments(self):
        return tuple(self.assignments.filter(is_active=True).only("role", "unit_id"))

    @cached_property
    def _roles_cache(self):
        roles = {assignment.role for assignment in self._active_role_assignments}
        if self.pk and getattr(self, "student_profile", None) is not None:
            roles.add(Role.STUDENT)
        return frozenset(roles)

    def roles(self):
        return self._roles_cache

    @cached_property
    def role(self):
        role_order = (
            Role.SUPER_ADMIN,
            Role.ADMIN,
            Role.DIRECTOR,
            Role.AUDITOR,
            Role.UNIT_MANAGER,
            Role.HOD,
            Role.BURSAR,
            Role.TEACHER,
            Role.CASHIER,
            Role.STUDENT,
        )
        return next((role for role in role_order if role in self.roles()), None)

    def has_role(self, *roles):
        return bool(self.roles().intersection(roles))

    def has_role_global(self, *roles):
        role_set = set(roles)
        return any(
            assignment.role in role_set and assignment.unit_id is None
            for assignment in self._active_role_assignments
        )

    def has_role_for_unit(self, role, unit_id):
        if unit_id is None:
            return False
        return any(
            assignment.role == role and assignment.unit_id == unit_id
            for assignment in self._active_role_assignments
        )

    def unit_ids_for(self, *roles):
        role_set = set(roles)
        return tuple(
            sorted(
                {
                    assignment.unit_id
                    for assignment in self._active_role_assignments
                    if assignment.role in role_set and assignment.unit_id is not None
                },
                key=str,
            )
        )

    def department_ids_for_hod(self):
        unit_ids = self.unit_ids_for(Role.HOD)
        if not unit_ids:
            return ()
        department_ids = self.role_scopes.filter(
            department__unit_id__in=unit_ids
        ).values_list("department_id", flat=True)
        return tuple(sorted(set(department_ids), key=str))

    def has_global_read(self):
        return self.has_role(*GLOBAL_READ_ROLES) or self.has_group_bursar_assignment()

    def has_group_bursar_assignment(self):
        return any(
            assignment.role == Role.BURSAR and assignment.unit_id is None
            for assignment in self._active_role_assignments
        )

    @cached_property
    def _unit_ids_cache(self):
        return tuple(
            sorted(
                {
                    assignment.unit_id
                    for assignment in self._active_role_assignments
                    if assignment.unit_id is not None
                },
                key=str,
            )
        )

    def unit_ids(self):
        return self._unit_ids_cache

    def clear_role_cache(self):
        for key in (
            "_active_role_assignments",
            "_roles_cache",
            "_unit_ids_cache",
            "role",
        ):
            self.__dict__.pop(key, None)

    def __str__(self):
        return self.email or self.firebase_uid


class RoleScope(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="role_scopes")
    department = models.ForeignKey(
        "org.Department", on_delete=models.CASCADE, related_name="role_scopes"
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("user", "department"), name="unique_user_department_scope"
            )
        ]

    def __str__(self):
        return f"{self.user} — {self.department}"


class RoleAssignment(BaseModel):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="assignments")
    role = models.CharField(max_length=20, choices=Role.choices)
    unit = models.ForeignKey(
        "org.BusinessUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="role_assignments",
    )
    is_active = models.BooleanField(default=True)
    granted_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("user", "role", "unit"),
                condition=Q(unit__isnull=False),
                name="uniq_assignment_unit",
            ),
            models.UniqueConstraint(
                fields=("user", "role"),
                condition=Q(unit__isnull=True),
                name="uniq_assignment_global",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        role__in=sorted(role.value for role in GLOBAL_ROLES),
                        unit__isnull=True,
                    )
                    | Q(
                        role__in=sorted(role.value for role in UNIT_SCOPED_ROLES),
                        unit__isnull=False,
                    )
                    | Q(role=Role.BURSAR)
                ),
                name="role_scope_valid",
            ),
        ]

    def __str__(self):
        return f"{self.user} — {self.role}" + (
            f" ({self.unit})" if self.unit_id else ""
        )
