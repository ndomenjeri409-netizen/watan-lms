from django.test import TestCase
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit, Department
from apps.people.models import Student


class UnitAuthorizationMatrixTests(TestCase):
    def setUp(self):
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
        self.student_user = User.objects.create_user("student")
        Student.objects.create(
            user=self.student_user,
            department=self.department_a,
            registration_number="INS-2026-0001",
            first_name="Student",
            last_name="One",
            email="student@example.test",
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

    @staticmethod
    def create_course(department, creator, title, code, published):
        return Course.objects.create(
            department=department,
            created_by=creator,
            title=title,
            code=code,
            status=Course.Status.PUBLISHED if published else Course.Status.DRAFT,
        )

    def response_as(self, user, method, url, data=None):
        self.client.force_authenticate(user)
        if method == "GET":
            return self.client.get(url)
        return self.client.post(url, data or {}, format="json")

    def test_role_matrix_limits_units_departments_and_courses(self):
        matrix = (
            # user, visible units, department status/rows, visible courses
            (
                self.manager_a,
                {"WTI"},
                200,
                {str(self.department_a.id)},
                {self.course_a.id, self.course_a_draft.id},
            ),
            (
                self.manager_b,
                {"WTA"},
                200,
                {str(self.department_b.id)},
                {self.course_b.id, self.course_b_draft.id},
            ),
            (
                self.auditor,
                {"WTI", "WTA"},
                200,
                {str(self.department_a.id), str(self.department_b.id)},
                {
                    self.course_a.id,
                    self.course_b.id,
                    self.course_a_draft.id,
                    self.course_b_draft.id,
                },
            ),
            (
                self.director,
                {"WTI", "WTA"},
                200,
                {str(self.department_a.id), str(self.department_b.id)},
                {
                    self.course_a.id,
                    self.course_b.id,
                    self.course_a_draft.id,
                    self.course_b_draft.id,
                },
            ),
            (
                self.group_bursar,
                {"WTI", "WTA"},
                403,
                set(),
                {
                    self.course_a.id,
                    self.course_b.id,
                    self.course_a_draft.id,
                    self.course_b_draft.id,
                },
            ),
            (
                self.unit_bursar,
                {"WTI"},
                403,
                set(),
                {self.course_a.id},
            ),
            (self.cashier, {"WTI"}, 403, set(), {self.course_a.id}),
            (
                self.teacher,
                {"WTI"},
                403,
                set(),
                {self.course_a.id, self.course_a_draft.id},
            ),
            (self.student_user, set(), 403, set(), {self.course_a.id}),
        )

        for user, units, department_status, department_ids, course_ids in matrix:
            with self.subTest(user=user.firebase_uid):
                units_response = self.response_as(user, "GET", "/api/v1/units")
                self.assertEqual(units_response.status_code, 200)
                self.assertEqual(
                    {item["code"] for item in units_response.json()["results"]}, units
                )

                department_response = self.response_as(
                    user, "GET", "/api/v1/departments/"
                )
                self.assertEqual(department_response.status_code, department_status)
                if department_status == 200:
                    self.assertEqual(
                        {item["id"] for item in department_response.json()["results"]},
                        department_ids,
                    )

                courses_response = self.response_as(user, "GET", "/api/v1/courses/")
                self.assertEqual(courses_response.status_code, 200)
                self.assertEqual(
                    {item["id"] for item in courses_response.json()["results"]},
                    {str(course_id) for course_id in course_ids},
                )

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
