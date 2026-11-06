from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role


class ApplicationPermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        role = getattr(request.user, "role", None)
        if action == "create":
            return True
        if action in {"approve", "reject"}:
            return role in ADMIN_ROLES | {Role.HOD}
        return request.method in SAFE_METHODS and role in ADMIN_ROLES | {
            Role.DIRECTOR,
            Role.HOD,
        }

    def has_object_permission(self, request, view, obj):
        if getattr(request.user, "role", None) == Role.HOD:
            return obj.department.role_scopes.filter(user=request.user).exists()
        return True


class EnrollmentPermission(BasePermission):
    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        action = getattr(view, "action", None)
        if action in {"transition"}:
            return role in ADMIN_ROLES | {Role.HOD, Role.STUDENT}
        return request.method in SAFE_METHODS and role in ADMIN_ROLES | {
            Role.DIRECTOR,
            Role.HOD,
            Role.TEACHER,
            Role.STUDENT,
        }

    def has_object_permission(self, request, view, obj):
        role = getattr(request.user, "role", None)
        if role == Role.HOD:
            return obj.course.department.role_scopes.filter(user=request.user).exists()
        if role == Role.TEACHER:
            return obj.course.created_by_id == request.user.id
        if role == Role.STUDENT:
            return obj.student.user_id == request.user.id
        return True
