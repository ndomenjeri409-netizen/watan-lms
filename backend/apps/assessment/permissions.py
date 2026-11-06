from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role


class AssessmentPermission(BasePermission):
    def has_permission(self, request, view):
        role = getattr(request.user, "role", None)
        action = getattr(view, "action", None)
        if action == "create":
            if view.__class__.__name__ == "SubmissionViewSet":
                return role == Role.STUDENT
            if view.__class__.__name__ == "GradeViewSet":
                return role in ADMIN_ROLES | {Role.TEACHER}
            return role in ADMIN_ROLES | {Role.HOD, Role.TEACHER}
        if view.__class__.__name__ == "GradeViewSet" and action in {
            "update",
            "partial_update",
        }:
            return role in ADMIN_ROLES | {Role.TEACHER}
        if action in {"create", "update", "partial_update"}:
            return role in ADMIN_ROLES | {Role.TEACHER}
        if action in {"submit_for_approval"}:
            return role in ADMIN_ROLES | {Role.TEACHER}
        if action in {"approve", "reject"}:
            return role in ADMIN_ROLES | {Role.HOD}
        if request.method in SAFE_METHODS:
            return role in ADMIN_ROLES | {
                Role.DIRECTOR,
                Role.HOD,
                Role.TEACHER,
                Role.STUDENT,
            }
        return role in ADMIN_ROLES | {Role.HOD, Role.TEACHER}


class GradebookPermission(BasePermission):
    def has_permission(self, request, view):
        return getattr(request.user, "role", None) in {
            Role.SUPER_ADMIN,
            Role.ADMIN,
            Role.DIRECTOR,
            Role.HOD,
            Role.TEACHER,
            Role.STUDENT,
        }
