from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role


class PeopleManagementPermission(BasePermission):
    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        if request.method in SAFE_METHODS:
            return role in ADMIN_ROLES | {Role.DIRECTOR, Role.HOD, Role.STUDENT}
        return role in ADMIN_ROLES | {Role.HOD, Role.STUDENT}

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == Role.STUDENT:
            if hasattr(obj, "student_id"):
                return obj.student.user_id == request.user.id
            return getattr(obj, "user_id", None) == request.user.id
        return True
