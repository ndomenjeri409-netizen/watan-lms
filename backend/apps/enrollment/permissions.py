from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role


class ApplicationPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        action = getattr(view, "action", None)
        if action == "create":
            return True
        if not user.is_authenticated:
            return False
        if action in {"approve", "reject"}:
            return user.has_role(*ADMIN_ROLES, Role.HOD, Role.UNIT_MANAGER)
        return request.method in SAFE_METHODS and user.has_role(
            *GLOBAL_READ_ROLES, Role.HOD, Role.UNIT_MANAGER
        )

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return True
        if (
            user.has_role(Role.HOD)
            and obj.department_id in user.department_ids_for_hod()
        ):
            return True
        return obj.course.unit_id in user.unit_ids_for(Role.UNIT_MANAGER)


class EnrollmentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        action = getattr(view, "action", None)
        if not user.is_authenticated:
            return False
        if action in {"transition"}:
            return user.has_role(
                *ADMIN_ROLES, Role.HOD, Role.UNIT_MANAGER, Role.STUDENT
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
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return True

        course = obj.course
        if (
            user.has_role(Role.HOD)
            and course.department_id in user.department_ids_for_hod()
        ):
            return True
        if user.has_role_for_unit(Role.UNIT_MANAGER, course.unit_id):
            return True
        if getattr(view, "action", None) == "transition":
            return user.has_role(Role.STUDENT) and obj.student.user_id == user.id
        if (
            user.has_role(Role.TEACHER)
            and course.teacher_assignments.filter(
                teacher=user, can_edit_content=True, is_active=True
            ).exists()
        ):
            return True
        return user.has_role(Role.STUDENT) and obj.student.user_id == user.id
