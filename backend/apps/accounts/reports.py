from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Course
from apps.accounts.roles import STAFF_ROLES, Role
from apps.assessment.models import Assessment, Submission
from apps.enrollment.models import Application, Enrollment
from apps.org.models import BusinessUnit, Department, Program
from apps.people.models import Student

from .serializers import ReportsOverviewSerializer

User = get_user_model()


class ReportsOverviewView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="unit",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Limit dashboard metrics to an authorized business unit.",
            )
        ],
        responses=ReportsOverviewSerializer,
    )
    def get(self, request):
        user = request.user
        if not user.roles():
            return Response({})

        selected_unit = request.query_params.get("unit")
        if selected_unit is not None:
            try:
                selected_unit = BusinessUnit._meta.pk.to_python(selected_unit)
            except (DjangoValidationError, TypeError, ValueError) as exc:
                raise ValidationError({"unit": "Select a valid unit."}) from exc
            permitted_units = BusinessUnit.objects.filter(
                pk=selected_unit, is_active=True
            )
            if not user.has_global_read():
                permitted_units = permitted_units.filter(pk__in=user.unit_ids())
            if not permitted_units.exists():
                raise ValidationError({"unit": "You may not access this unit."})

        overview = {}
        if user.has_role(
            Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.HOD, Role.UNIT_MANAGER
        ):
            if user.has_role(Role.UNIT_MANAGER):
                manager_unit_ids = (
                    (selected_unit,) if selected_unit is not None else user.unit_ids()
                )
                departments = Department.objects.filter(unit_id__in=manager_unit_ids)
                programs = Program.objects.filter(
                    department__unit_id__in=manager_unit_ids
                )
                courses = Course.objects.filter(
                    department__unit_id__in=manager_unit_ids
                )
                students = Student.objects.filter(
                    department__unit_id__in=manager_unit_ids
                )
                applications = Application.objects.filter(
                    department__unit_id__in=manager_unit_ids
                )
                enrollments = Enrollment.objects.filter(
                    course__department__unit_id__in=manager_unit_ids
                )
            else:
                departments = Department.objects.for_user(user)
                programs = Program.objects.for_user(user)
                courses = Course.objects.for_user(user)
                students = Student.objects.for_user(user)
                applications = Application.objects.for_user(user)
                enrollments = Enrollment.objects.for_user(user)

            departments = departments.filter(is_active=True)
            programs = programs.filter(is_active=True)
            courses = courses.filter(is_active=True, status=Course.Status.PUBLISHED)
            students = students.filter(is_active=True)
            applications = applications.filter(status=Application.Status.PENDING)
            enrollments = enrollments.filter(status=Enrollment.Status.PENDING)
            if selected_unit is not None:
                departments = departments.filter(unit_id=selected_unit)
                programs = programs.filter(department__unit_id=selected_unit)
                courses = courses.filter(department__unit_id=selected_unit)
                students = students.filter(department__unit_id=selected_unit)
                applications = applications.filter(department__unit_id=selected_unit)
                enrollments = enrollments.filter(
                    course__department__unit_id=selected_unit
                )
            overview["departments"] = departments.count()
            overview["programs"] = programs.count()
            overview["courses"] = courses.count()
            overview["students"] = students.count()
            overview["pending_applications"] = applications.count()
            overview["pending_enrollments"] = enrollments.count()

        if user.has_role(Role.SUPER_ADMIN, Role.ADMIN):
            visible_users = User.objects.for_user(user).filter(is_active=True)
            if selected_unit is not None:
                visible_users = visible_users.filter(
                    assignments__is_active=True,
                    assignments__unit_id=selected_unit,
                ).distinct()
            overview["users"] = visible_users.count()
            overview["staff"] = (
                visible_users.filter(
                    assignments__is_active=True,
                    assignments__role__in=STAFF_ROLES,
                )
                .exclude(assignments__role__in={Role.SUPER_ADMIN, Role.ADMIN})
                .distinct()
                .count()
            )

        if user.has_role(Role.TEACHER):
            teacher_courses = Course.objects.for_user(user).filter(
                is_active=True, status=Course.Status.PUBLISHED
            )
            if selected_unit is not None:
                teacher_courses = teacher_courses.filter(
                    department__unit_id=selected_unit
                )
            overview["courses"] = teacher_courses.count()
            teacher_assessments = Assessment.objects.for_user(user).filter(
                status=Assessment.Status.PUBLISHED
            )
            if selected_unit is not None:
                teacher_assessments = teacher_assessments.filter(
                    course__department__unit_id=selected_unit
                )
            teacher_submissions = Submission.objects.for_user(user).filter(
                assessment__in=teacher_assessments
            )
            overview["submissions_to_grade"] = teacher_submissions.exclude(
                grade__isnull=False
            ).count()
            overview["assessments"] = teacher_assessments.count()

        if user.has_role(Role.STUDENT):
            from apps.enrollment.models import CourseAccess

            overview["courses"] = (
                CourseAccess.objects.for_user(user).filter(is_active=True).count()
            )

        return Response(overview)
