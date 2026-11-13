from rest_framework.exceptions import PermissionDenied

from ..roles import Role


def may_assign_role(actor, role, target=None):
    if actor.has_role_global(Role.SUPER_ADMIN):
        return True
    if not actor.has_role_global(Role.ADMIN) or role in {
        Role.SUPER_ADMIN,
        Role.ADMIN,
    }:
        return False
    return target is None or not target.has_role_global(
        Role.SUPER_ADMIN, Role.ADMIN
    )


def assert_role_assignment(actor, role, target=None):
    if role not in Role.values:
        raise PermissionDenied("Unknown role.")
    if not may_assign_role(actor, role, target):
        raise PermissionDenied("You may not assign this role.")
