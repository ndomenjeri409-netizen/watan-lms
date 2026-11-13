from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role

FINANCE_READ_ROLES = GLOBAL_READ_ROLES | {
    Role.BURSAR,
    Role.UNIT_MANAGER,
    Role.CASHIER,
}
FINANCE_WRITE_ROLES = ADMIN_ROLES | {Role.BURSAR, Role.UNIT_MANAGER}


def finance_unit_ids(user):
    return user.unit_ids_for(Role.BURSAR, Role.UNIT_MANAGER, Role.CASHIER)


def can_manage_unit(user, unit):
    if user.has_role(*ADMIN_ROLES):
        return True
    if user.has_group_bursar_assignment():
        return True
    return (
        unit is not None
        and unit.pk in finance_unit_ids(user)
        and user.has_role(Role.BURSAR, Role.UNIT_MANAGER, Role.CASHIER)
    )


class FinancePermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        action = getattr(view, "action", None)
        if request.method in SAFE_METHODS:
            return user.has_role(*FINANCE_READ_ROLES) or (
                getattr(view, "student_read_only", False)
                and user.has_role(Role.STUDENT)
            )
        if action == "create" and getattr(view, "basename", "") == "payment":
            return user.has_role(*FINANCE_WRITE_ROLES, Role.CASHIER)
        if action in {"approve", "reverse", "void"}:
            return user.has_role(*ADMIN_ROLES, Role.UNIT_MANAGER)
        return user.has_role(*FINANCE_WRITE_ROLES)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        unit = getattr(obj, "unit", None)
        if unit is None and hasattr(obj, "invoice"):
            unit = obj.invoice.unit
        if unit is None and hasattr(obj, "payment"):
            unit = obj.payment.invoice.unit
        return can_manage_unit(request.user, unit)
