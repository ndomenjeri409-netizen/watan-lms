from pathlib import Path

import yaml
from django.test import TestCase
from rest_framework.test import APIClient

from apps.academics.models import Course, CourseAssignment
from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.enrollment.models import Enrollment
from apps.org.models import BusinessUnit, Department
from apps.people.models import Student
from apps.scheduling.models import ClassGroup, ClassTeacher

MATRIX_PATH = Path(__file__).with_name("authz_matrix.yaml")


class UnitAuthorizationMatrixTests(TestCase):
    def setUp(self):
        with MATRIX_PATH.open(encoding="utf-8") as matrix_file:
            self.matrix = yaml.safe_load(matrix_file)
        self.client = APIClient()
        self.unit_a = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.unit_b = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        self.department_a = Department.objects.create(
            unit=self.unit_a, name="Institute Department", code="INS"
        )
        self.department_b = Department.objects.create(
            unit=self.unit_b, name="Travel Department", code="TRV"
        )
        self.admin = User.objects.create_user("matrix-admin", role=Role.ADMIN)
        self.super_admin = User.objects.create_user(
            "matrix-super-admin", role=Role.SUPER_ADMIN
        )
        self.awaiting = User.objects.create_user("matrix-awaiting")
        self.manager_a = User.objects.create_user(
            "manager-a", role=Role.UNIT_MANAGER, unit=self.unit_a
        )
        self.manager_b = User.objects.create_user(
            "manager-b", role=Role.UNIT_MANAGER, unit=self.unit_b
        )
        self.auditor = User.objects.create_user("auditor", role=Role.AUDITOR)
        self.director = User.objects.create_user("director", role=Role.DIRECTOR)
        self.group_bursar = User.objects.create_user("group-bursar", role=Role.BURSAR)
        self.unit_bursar = User.objects.create_user(
            "unit-bursar", role=Role.BURSAR, unit=self.unit_a
        )
        self.cashier = User.objects.create_user(
            "cashier", role=Role.CASHIER, unit=self.unit_a
        )
        self.teacher = User.objects.create_user(
            "teacher", role=Role.TEACHER, unit=self.unit_a
        )
        self.hod = User.objects.create_user("hod", role=Role.HOD, unit=self.unit_a)
        RoleScope.objects.create(user=self.hod, department=self.department_a)
        self.student_user = User.objects.create_user("student")
        self.student_user_other = User.objects.create_user("student-other")
        self.student_a = Student.objects.create(
            user=self.student_user,
            department=self.department_a,
            registration_number="INS-2026-0001",
            first_name="Student",
            last_name="One",
            email="student@example.test",
            admission_year=2026,
        )
        self.student_b = Student.objects.create(
            user=self.student_user_other,
            department=self.department_b,
            registration_number="TRV-2026-0001",
            first_name="Other",
            last_name="Student",
            email="other-student@example.test",
            admission_year=2026,
        )

        self.course_a = self.create_course(
            self.department_a, self.admin, "Institute course", "INST", True
        )
        self.course_b = self.create_course(
            self.department_b, self.admin, "Travel course", "TRVL", True
        )
        self.course_a_draft = self.create_course(
            self.department_a, self.teacher, "Institute draft", "INSD", False
        )
        self.course_b_draft = self.create_course(
            self.department_b, self.teacher, "Travel draft", "TRVD", False
        )
        self.class_group = ClassGroup.objects.create(
            course=self.course_a,
            name="Matrix class",
            code="MATRIX-A",
        )
        Enrollment.objects.create(
            student=self.student_a,
            course=self.course_a,
            class_group=self.class_group,
            status=Enrollment.Status.ACTIVE,
        )
        ClassTeacher.objects.create(
            class_group=self.class_group,
            teacher=self.teacher,
            role=ClassTeacher.Role.LEAD,
        )
        self.multi_role_user = User.objects.create_user("multi-role")
        self.multi_role_user.assignments.create(
            role=Role.UNIT_MANAGER, unit=self.unit_b
        )
        self.multi_role_user.assignments.create(role=Role.TEACHER, unit=self.unit_a)
        self.multi_role_user.clear_role_cache()
        CourseAssignment.objects.create(
            course=self.course_a_draft,
            teacher=self.multi_role_user,
            can_edit_content=True,
        )
        ClassTeacher.objects.create(
            class_group=self.class_group,
            teacher=self.multi_role_user,
            role=ClassTeacher.Role.ASSISTANT,
        )
        self.actor_profiles = {
            "anonymous": None,
            "awaiting": self.awaiting,
            "super_admin": self.super_admin,
            "admin": self.admin,
            "director": self.director,
            "auditor": self.auditor,
            "unit_manager_own": self.manager_a,
            "unit_manager_other": self.manager_b,
            "hod": self.hod,
            "teacher": self.teacher,
            "bursar_unit": self.unit_bursar,
            "bursar_group": self.group_bursar,
            "cashier": self.cashier,
            "student_self": self.student_user,
            "student_other": self.student_user_other,
            "multi_role": self.multi_role_user,
        }

    @staticmethod
    def create_course(department, creator, title, code, published):
        course = Course.objects.create(
            department=department,
            created_by=creator,
            title=title,
            code=code,
            status=Course.Status.PUBLISHED if published else Course.Status.DRAFT,
        )
        if creator.assignments.filter(
            role=Role.TEACHER,
            unit=department.unit,
            is_active=True,
        ).exists():
            CourseAssignment.objects.create(
                course=course,
                teacher=creator,
                can_edit_content=True,
            )
        return course

    def response_as(self, user, method, url, data=None):
        self.client.force_authenticate(user)
        if method == "GET":
            return self.client.get(url)
        return self.client.post(url, data or {}, format="json")

    def test_role_matrix_limits_units_departments_and_courses(self):
        expected_profiles = set(self.matrix["actor_profiles"])
        self.assertEqual(set(self.actor_profiles), expected_profiles)
        for probe in self.matrix["scoped_reads"]:
            if probe.get("rows_are_finance_fixture_ids"):
                continue
            self.assertEqual(set(probe["expected"]), expected_profiles)
            for profile, expected in probe["expected"].items():
                with self.subTest(profile=profile, path=probe["path"]):
                    self.client.force_authenticate(self.actor_profiles[profile])
                    response = self.client.get(probe["path"])
                    self.assertEqual(response.status_code, expected["status"])
                    if response.status_code == 200:
                        rows = {
                            row[probe["result_field"]]
                            for row in response.json()["results"]
                        }
                        expected_rows = set(expected["rows"])
                        if probe.get("rows_are_actor_profiles"):
                            expected_rows = {
                                str(self.actor_profiles[profile].pk)
                                for profile in expected_rows
                            }
                        self.assertEqual(rows, expected_rows)

    def test_read_only_and_unit_users_cannot_write_across_units(self):
        for user in (
            self.manager_a,
            self.manager_b,
            self.auditor,
            self.director,
            self.group_bursar,
            self.unit_bursar,
            self.cashier,
            self.teacher,
            self.student_user,
        ):
            with self.subTest(user=user.firebase_uid):
                response = self.response_as(
                    user,
                    "POST",
                    "/api/v1/departments/",
                    {
                        "unit": str(self.unit_b.id),
                        "name": f"New {user.firebase_uid}",
                        "code": f"N{user.firebase_uid[-3:].upper()}",
                    },
                )
                self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(self.auditor)
        course_update = self.client.patch(
            f"/api/v1/courses/{self.course_b.slug}/",
            {"title": "Changed"},
            format="json",
        )
        self.assertEqual(course_update.status_code, 403)

    def test_multi_unit_user_sees_only_assigned_unit_courses(self):
        multi_unit_user = User.objects.create_user("multi-unit-user")
        multi_unit_user.assignments.create(role=Role.UNIT_MANAGER, unit=self.unit_a)
        multi_unit_user.assignments.create(role=Role.UNIT_MANAGER, unit=self.unit_b)
        multi_unit_user.clear_role_cache()

        response = self.response_as(multi_unit_user, "GET", "/api/v1/courses/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["results"]},
            {
                str(self.course_a.id),
                str(self.course_b.id),
                str(self.course_a_draft.id),
                str(self.course_b_draft.id),
            },
        )
