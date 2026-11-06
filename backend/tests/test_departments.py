from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit, Campus, Department, Program


class DepartmentManagementTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.client.force_authenticate(self.admin)
        self.campus = Campus.objects.create(name="Main", code="MAIN")
        self.unit = BusinessUnit.objects.create(
            code="MAIN", name="Main Unit", kind=BusinessUnit.Kind.ACADEMIC
        )

    def create_department(self, name="Travel", code="TRV"):
        return Department.objects.create(
            unit=self.unit, campus=self.campus, name=name, code=code
        )

    def test_create_normalizes_code_and_rejects_invalid_code(self):
        response = self.client.post(
            "/api/v1/departments/",
            {
                "name": "Travel",
                "code": "trv",
                "campus": str(self.campus.id),
                "unit": str(self.unit.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["code"], "TRV")

        invalid_response = self.client.post(
            "/api/v1/departments/",
            {"name": "Hospitality", "code": "T&T", "unit": str(self.unit.id)},
            format="json",
        )
        self.assertEqual(invalid_response.status_code, 400)
        self.assertIn("code", invalid_response.json()["fields"])

    def test_create_requires_a_unit(self):
        response = self.client.post(
            "/api/v1/departments/",
            {"name": "Hospitality", "code": "HSP"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unit", response.json()["fields"])

    def test_department_name_and_code_are_unique_ignoring_case(self):
        self.create_department()

        duplicate_name = self.client.post(
            "/api/v1/departments/",
            {"name": "travel", "code": "NEW", "unit": str(self.unit.id)},
            format="json",
        )
        duplicate_code = self.client.post(
            "/api/v1/departments/",
            {"name": "Hospitality", "code": "trv", "unit": str(self.unit.id)},
            format="json",
        )

        self.assertEqual(duplicate_name.status_code, 400)
        self.assertIn("name", duplicate_name.json()["fields"])
        self.assertEqual(duplicate_code.status_code, 400)
        self.assertIn("code", duplicate_code.json()["fields"])

    def test_list_searches_and_returns_program_course_counts(self):
        department = self.create_department()
        Program.objects.create(department=department, name="Tourism", code="TOUR")

        response = self.client.get("/api/v1/departments/?search=trav&page=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 1)
        result = response.json()["results"][0]
        self.assertEqual(result["program_count"], 1)
        self.assertEqual(result["course_count"], 0)

    def test_unit_filter_is_validated_against_the_users_assignments(self):
        other_unit = BusinessUnit.objects.create(
            code="WTA", name="Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        self.create_department()
        Department.objects.create(unit=other_unit, name="Hospitality", code="HSP")
        manager = User.objects.create_user(
            "manager", role=Role.UNIT_MANAGER, unit=self.unit
        )
        self.client.force_authenticate(manager)

        scoped = self.client.get(f"/api/v1/departments/?unit={self.unit.pk}")
        forbidden = self.client.get(f"/api/v1/departments/?unit={other_unit.pk}")

        self.assertEqual(scoped.status_code, 200)
        self.assertEqual(scoped.json()["count"], 1)
        self.assertEqual(forbidden.status_code, 400)

    def test_archive_is_hidden_by_default_and_included_on_request(self):
        department = self.create_department()

        archive_response = self.client.delete(f"/api/v1/departments/{department.id}/")

        self.assertEqual(archive_response.status_code, 204)
        department.refresh_from_db()
        self.assertIsNotNone(department.archived_at)
        self.assertFalse(department.is_active)
        self.assertEqual(self.client.get("/api/v1/departments/").json()["count"], 0)
        archived_response = self.client.get("/api/v1/departments/?show_archived=true")
        self.assertEqual(archived_response.json()["count"], 1)
        self.assertEqual(
            archived_response.json()["results"][0]["id"], str(department.id)
        )
