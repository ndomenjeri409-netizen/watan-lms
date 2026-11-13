from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role


class AttendancePermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        action = getattr(view, "action", None)
        if action == "check_in" or view.__class__.__name__ == "CheckInView":
            return user.has_role(Role.STUDENT)
        if action in {"open", "qr", "close", "mark"}:
            return user.has_role(
                *ADMIN_ROLES, Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
            )
        return request.method in SAFE_METHODS and user.has_role(
            *GLOBAL_READ_ROLES,
            Role.HOD,
            Role.UNIT_MANAGER,
            Role.TEACHER,
            Role.STUDENT,
        )

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True

        session = obj if hasattr(obj, "class_group") else getattr(obj, "session", None)
        if session is None:
            return False
        class_group = session.class_group
        if user.has_role_global(*ADMIN_ROLES):
            return True
        if (
            user.has_role(Role.HOD)
            and class_group.course.department_id in user.department_ids_for_hod()
        ):
            return True
        if user.has_role_for_unit(Role.UNIT_MANAGER, class_group.course.unit_id):
            return True
        return user.has_role(Role.TEACHER) and class_group.has_teacher(user)
