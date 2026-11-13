from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role


class AssessmentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False

        action = getattr(view, "action", None)
        if action == "create":
            if view.__class__.__name__ == "SubmissionViewSet":
                return user.has_role(Role.STUDENT)
            if view.__class__.__name__ == "GradeViewSet":
                return user.has_role_global(*ADMIN_ROLES) or user.has_role(
                    Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
                )
            return user.has_role_global(*ADMIN_ROLES) or user.has_role(
                Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
            )
        if view.__class__.__name__ == "GradeViewSet" and action in {
            "update",
            "partial_update",
        }:
            return user.has_role_global(*ADMIN_ROLES) or user.has_role(
                Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
            )
        if action in {"update", "partial_update"}:
            return user.has_role_global(*ADMIN_ROLES) or user.has_role(
                Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
            )
        if action == "submit_for_approval":
            return user.has_role_global(*ADMIN_ROLES) or user.has_role(Role.TEACHER)
        if action in {"approve", "reject"}:
            return user.has_role_global(*ADMIN_ROLES) or user.has_role(
                Role.HOD, Role.UNIT_MANAGER
            )
        if request.method in SAFE_METHODS:
            return user.has_role_global(*GLOBAL_READ_ROLES) or user.has_role(
                Role.HOD, Role.UNIT_MANAGER, Role.TEACHER, Role.STUDENT
            )
        return user.has_role_global(*ADMIN_ROLES) or user.has_role(
            Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
        )


class GradebookPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and (
            user.has_role_global(*GLOBAL_READ_ROLES)
            or user.has_role(Role.HOD, Role.UNIT_MANAGER, Role.TEACHER, Role.STUDENT)
        )
