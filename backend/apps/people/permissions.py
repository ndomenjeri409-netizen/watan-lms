from django.db.models import Q
from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from apps.people.models import Guardian, StaffProfile, Student


def can_register_in_unit(user, unit, department_id=None):
    if user.has_role_global(Role.SUPER_ADMIN, Role.ADMIN):
        return True
    if user.has_role_for_unit(Role.UNIT_MANAGER, unit.pk):
        return True
    return (
        user.has_role(Role.HOD)
        and department_id is not None
        and department_id in user.department_ids_for_hod()
    )


def may_read_restricted_student(user, student):
    if user.has_role_global(Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.AUDITOR):
        return True
    unit_ids = user.unit_ids_for(Role.UNIT_MANAGER, Role.BURSAR)
    if not unit_ids:
        return False
    return (
        Student.objects.filter(pk=student.pk)
        .filter(
            Q(home_unit_id__in=unit_ids)
            | Q(enrollments__unit_id__in=unit_ids)
            | Q(invoices__unit_id__in=unit_ids)
        )
        .exists()
    )


def may_manage_student(user, student):
    if user.has_role_global(Role.SUPER_ADMIN, Role.ADMIN):
        return True
    unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
    if (
        unit_ids
        and Student.objects.filter(pk=student.pk)
        .filter(
            Q(home_unit_id__in=unit_ids)
            | Q(enrollments__unit_id__in=unit_ids)
            | Q(invoices__unit_id__in=unit_ids)
        )
        .exists()
    ):
        return True
    if (
        user.has_role(Role.HOD)
        and student.enrollments.filter(
            course__department_id__in=user.department_ids_for_hod()
        ).exists()
    ):
        return True
    return user.has_role(Role.STUDENT) and student.user_id == user.pk


class PeopleManagementPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False

        model = getattr(getattr(view, "queryset", None), "model", None)
        if request.method in SAFE_METHODS:
            if user.has_role_global(*GLOBAL_READ_ROLES):
                return True
            if model is StaffProfile:
                return user.has_role(Role.UNIT_MANAGER, Role.HOD)
            if model is Guardian:
                return user.has_role(Role.UNIT_MANAGER, Role.BURSAR)
            return user.has_role(
                Role.UNIT_MANAGER,
                Role.HOD,
                Role.TEACHER,
                Role.BURSAR,
                Role.CASHIER,
                Role.STUDENT,
            )

        if user.has_role_global(Role.SUPER_ADMIN, Role.ADMIN):
            return True
        action = getattr(view, "action", None)
        if action in {
            "create",
            "import_students",
            "enroll_in_unit",
            "duplicate_lookup",
        }:
            return user.has_role(Role.HOD, Role.UNIT_MANAGER)
        if action == "transfer":
            return user.has_role(Role.UNIT_MANAGER)
        if action in {"invite", "change_status"}:
            return user.has_role(Role.HOD, Role.UNIT_MANAGER)
        if model is Guardian:
            return user.has_role(Role.UNIT_MANAGER)
        return False

    def has_object_permission(self, request, view, obj):
        action = getattr(view, "action", None)
        if isinstance(obj, Student) and action == "transfer":
            return request.user.has_role_global(
                Role.SUPER_ADMIN, Role.ADMIN
            ) or request.user.has_role(Role.UNIT_MANAGER)
        if isinstance(obj, Student) and action in {"invite", "change_status"}:
            return may_manage_student(request.user, obj)
        if isinstance(obj, Guardian):
            if request.method in SAFE_METHODS and request.user.has_role_global(
                *GLOBAL_READ_ROLES
            ):
                return True
            if request.method in SAFE_METHODS:
                return request.user.has_role(Role.UNIT_MANAGER, Role.BURSAR)
            return may_manage_student(request.user, obj.student)
        return True
