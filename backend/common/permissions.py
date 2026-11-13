from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role


class OrgManagementPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return user.has_role_global(*GLOBAL_READ_ROLES) or user.has_role(
                Role.UNIT_MANAGER, Role.HOD
            )
        return user.has_role_global(*ADMIN_ROLES)


class ReadOnlyRoleWritePermission(BasePermission):
    read_only_roles = frozenset((Role.DIRECTOR, Role.AUDITOR))

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or not request.user.is_authenticated:
            return True
        roles = request.user.roles()
        return not roles or not roles.issubset(self.read_only_roles)


class UserManagementPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if getattr(view, "action", None) in {"invite", "role"}:
            return user.has_role_global(*ADMIN_ROLES)
        return user.has_role_global(
            Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR
        ) or user.has_role(Role.HOD, Role.UNIT_MANAGER)

    def has_object_permission(self, request, view, obj):
        if getattr(view, "action", None) != "role":
            return True
        user = request.user
        if user.has_role_global(Role.SUPER_ADMIN):
            return True
        return user.has_role_global(Role.ADMIN) and not obj.has_role_global(
            Role.SUPER_ADMIN, Role.ADMIN
        )
