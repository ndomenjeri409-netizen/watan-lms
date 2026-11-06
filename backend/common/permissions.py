from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role


class OrgManagementPermission(BasePermission):
    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        if request.method in SAFE_METHODS:
            return role in {
                Role.SUPER_ADMIN,
                Role.ADMIN,
                Role.DIRECTOR,
                Role.AUDITOR,
                Role.UNIT_MANAGER,
                Role.HOD,
            }
        return role in ADMIN_ROLES


class UserManagementPermission(BasePermission):
    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        if getattr(view, "action", None) in {"invite", "role"}:
            return role in ADMIN_ROLES
        return role in {
            Role.SUPER_ADMIN,
            Role.ADMIN,
            Role.DIRECTOR,
            Role.HOD,
        }

    def has_object_permission(self, request, view, obj):
        if getattr(view, "action", None) != "role":
            return True
        if request.user.role == Role.SUPER_ADMIN:
            return True
        return request.user.role == Role.ADMIN and obj.role not in {
            Role.SUPER_ADMIN,
            Role.ADMIN,
        }
