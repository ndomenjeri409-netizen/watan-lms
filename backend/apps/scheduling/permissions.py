from rest_framework.permissions import SAFE_METHODS, BasePermission

from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role

from .models import ClassGroup, ClassTeacher, Room, TimetableSlot


def can_manage_department_schedule(user, department):
    if department is None:
        return user.has_role_global(*ADMIN_ROLES)
    return (
        user.has_role_global(*ADMIN_ROLES)
        or (user.has_role(Role.HOD) and department.pk in user.department_ids_for_hod())
        or user.has_role_for_unit(Role.UNIT_MANAGER, department.unit_id)
    )


def can_manage_course_schedule(user, course):
    return can_manage_department_schedule(user, course.department) or (
        user.has_role(Role.TEACHER)
        and course.teacher_assignments.filter(
            teacher=user, can_edit_content=True, is_active=True
        ).exists()
    )


def can_manage_scheduled_class(user, class_group):
    return can_manage_department_schedule(user, class_group.course.department) or (
        user.has_role(Role.TEACHER) and class_group.has_teacher(user)
    )


class SchedulingPermission(BasePermission):
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return user.has_role(
                *GLOBAL_READ_ROLES,
                Role.HOD,
                Role.UNIT_MANAGER,
                Role.TEACHER,
                Role.STUDENT,
            )
        if getattr(view, "assignment_management", False):
            return user.has_role(*ADMIN_ROLES, Role.HOD, Role.UNIT_MANAGER)
        if getattr(view, "teacher_schedule_management", False):
            return user.has_role(
                *ADMIN_ROLES, Role.HOD, Role.UNIT_MANAGER, Role.TEACHER
            )
        return user.has_role(*ADMIN_ROLES, Role.HOD, Role.UNIT_MANAGER)

    def has_object_permission(self, request, view, obj):
        user = request.user
        if not user.is_authenticated:
            return False
        if request.method in SAFE_METHODS:
            return True
        if isinstance(obj, Room):
            return can_manage_department_schedule(user, obj.department)
        if isinstance(obj, ClassGroup):
            return can_manage_course_schedule(user, obj.course)
        if isinstance(obj, ClassTeacher):
            return can_manage_department_schedule(
                user, obj.class_group.course.department
            )
        if isinstance(obj, TimetableSlot):
            return can_manage_scheduled_class(user, obj.class_group)
        return False


class ClassTeacherPermission(SchedulingPermission):
    pass
