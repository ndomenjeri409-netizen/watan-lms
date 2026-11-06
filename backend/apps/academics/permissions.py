from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, Role

from .models import Course, CourseModule, Lesson, Material, Unit


def get_course(instance):
    if isinstance(instance, Course):
        return instance
    if isinstance(instance, CourseModule):
        return instance.course
    if isinstance(instance, Unit):
        return instance.module.course
    if isinstance(instance, Lesson):
        return instance.unit.module.course
    if isinstance(instance, Material):
        return instance.lesson.unit.module.course
    return None


def may_manage_course(user, course):
    if user.role in ADMIN_ROLES:
        return True
    if user.role == Role.HOD:
        return course.department.role_scopes.filter(user=user).exists()
    if user.role == Role.TEACHER:
        return course.created_by_id == user.id
    return False


class AcademicsPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        role = getattr(request.user, "role", None)
        if getattr(view, "action", None) == "create":
            allowed_roles = ADMIN_ROLES | {Role.HOD}
            if getattr(view, "teacher_content_management", False):
                allowed_roles.add(Role.TEACHER)
            return role in allowed_roles
        return role in ADMIN_ROLES | {Role.HOD, Role.TEACHER}

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        course = get_course(obj)
        return bool(course and may_manage_course(request.user, course))
