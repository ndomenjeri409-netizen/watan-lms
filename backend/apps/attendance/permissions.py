from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role


class AttendancePermission(BasePermission):
    def has_permission(self, request, view):
        action = getattr(view, "action", None)
        role = getattr(request.user, "role", None)
        if action == "check_in" or view.__class__.__name__ == "CheckInView":
            return role == Role.STUDENT
        if action in {"open", "qr", "close"}:
            return role in ADMIN_ROLES | {Role.HOD, Role.TEACHER}
        return request.method in SAFE_METHODS and role in ADMIN_ROLES | {
            Role.DIRECTOR,
            Role.HOD,
            Role.TEACHER,
            Role.STUDENT,
        }

    def has_object_permission(self, request, view, obj):
        role = getattr(request.user, "role", None)
        session = obj if hasattr(obj, "class_group") else getattr(obj, "session", None)
        if session is None:
            return False
        if role == Role.HOD:
            return session.class_group.course.department.role_scopes.filter(
                user=request.user
            ).exists()
        if role == Role.TEACHER:
            return session.class_group.teacher_id == request.user.id
        if role == Role.STUDENT and request.method in SAFE_METHODS:
            student = getattr(obj, "student", None)
            return bool(student and student.user_id == request.user.id)
        return role in ADMIN_ROLES | {Role.DIRECTOR}
