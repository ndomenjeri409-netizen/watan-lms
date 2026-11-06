from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role


class SchedulingPermission(BasePermission):
    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        if request.method in SAFE_METHODS:
            return role in ADMIN_ROLES | {
                Role.DIRECTOR,
                Role.HOD,
                Role.TEACHER,
                Role.STUDENT,
            }
        if getattr(view, "teacher_schedule_management", False):
            return role in ADMIN_ROLES | {Role.HOD, Role.TEACHER}
        return role in ADMIN_ROLES | {Role.HOD}

    def has_object_permission(self, request, view, obj):
        role = getattr(request.user, "role", None)
        if request.method in SAFE_METHODS:
            return True
        if role in ADMIN_ROLES:
            return True
        if role == Role.HOD:
            department = getattr(obj, "department", None)
            if department is None and hasattr(obj, "course"):
                department = obj.course.department
            if department is None and hasattr(obj, "class_group"):
                department = obj.class_group.course.department
            return bool(
                department and department.role_scopes.filter(user=request.user).exists()
            )
        if role == Role.TEACHER and getattr(view, "teacher_schedule_management", False):
            if hasattr(obj, "class_group"):
                return obj.class_group.teacher_id == request.user.id
            if hasattr(obj, "course"):
                return obj.course.created_by_id == request.user.id
        return False
