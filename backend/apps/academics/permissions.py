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


def may_manage_course_department(user, department):
    if user.has_role_global(*ADMIN_ROLES):
        return True
    return department.pk in user.department_ids_for_hod() or user.has_role_for_unit(
        Role.UNIT_MANAGER, department.unit_id
    )


def may_manage_course(user, course):
    if may_manage_course_department(user, course.department):
        return True
    if user.has_role_for_unit(Role.TEACHER, course.unit_id):
        from .models import CourseAssignment

        return CourseAssignment.objects.filter(
            course=course,
            teacher=user,
            can_edit_content=True,
            is_active=True,
        ).exists()
    return False


class AcademicsPermission(BasePermission):
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        user = request.user
        if not user.is_authenticated:
            return False
        if user.has_role_global(*ADMIN_ROLES):
            return True
        if getattr(view, "action", None) == "create":
            return user.has_role(Role.HOD, Role.UNIT_MANAGER) or (
                getattr(view, "teacher_content_management", False)
                and user.has_role(Role.TEACHER)
            )
        return user.has_role(Role.HOD, Role.UNIT_MANAGER, Role.TEACHER)

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        course = get_course(obj)
        return bool(course and may_manage_course(request.user, course))


class CourseAssignmentPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return user.has_role_global(*ADMIN_ROLES, Role.DIRECTOR, Role.AUDITOR) or (
                user.has_role(Role.HOD, Role.UNIT_MANAGER, Role.TEACHER)
            )
        return user.has_role_global(*ADMIN_ROLES) or user.has_role(
            Role.HOD, Role.UNIT_MANAGER
        )

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS:
            return True
        return may_manage_course(request.user, obj.course)
