from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit, Campus, Department, Program
from tests.helpers import create_role_user


class ReportsOverviewTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        self.unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        other_unit = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        self.department_a = Department.objects.create(
            unit=self.unit, campus=campus, name="Travel", code="TRV"
        )
        self.department_b = Department.objects.create(
            unit=other_unit, campus=campus, name="Hospitality", code="HSP"
        )
        Program.objects.create(
            department=self.department_a, name="Tourism", code="TOUR"
        )
        Program.objects.create(
            department=self.department_b, name="Hotel Operations", code="HOTEL"
        )
        self.hod = create_role_user("hod", role=Role.HOD)
        RoleScope.objects.create(user=self.hod, department=self.department_a)

    def test_management_metrics_are_limited_to_the_hods_department_scope(self):
        self.client.force_authenticate(self.hod)

        response = self.client.get("/api/v1/reports/overview")

        self.assertEqual(response.status_code, 200)
        overview = response.json()
        self.assertEqual(overview["departments"], 1)
        self.assertEqual(overview["programs"], 1)
        self.assertNotIn("users", overview)
        self.assertNotIn("staff", overview)

    def test_admin_receives_only_metrics_backed_by_existing_models(self):
        admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.client.force_authenticate(admin)

        response = self.client.get("/api/v1/reports/overview")

        self.assertEqual(response.status_code, 200)
        overview = response.json()
        self.assertEqual(overview["departments"], 2)
        self.assertEqual(overview["programs"], 2)
        self.assertEqual(overview["users"], 2)
        self.assertEqual(overview["staff"], 1)
        self.assertNotIn("fee_balance", overview)
        self.assertNotIn("announcements", overview)

    def test_user_without_a_role_gets_no_dashboard_metrics(self):
        user = User.objects.create_user("awaiting-approval")
        self.client.force_authenticate(user)

        response = self.client.get("/api/v1/reports/overview")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {})

    def test_group_dashboard_metrics_can_be_filtered_to_a_unit(self):
        admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.client.force_authenticate(admin)

        response = self.client.get(f"/api/v1/reports/overview?unit={self.unit.pk}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["departments"], 1)
        self.assertEqual(response.json()["programs"], 1)

    def test_unit_manager_dashboard_metrics_are_limited_to_assigned_unit(self):
        manager = create_role_user("manager", role=Role.UNIT_MANAGER)
        self.client.force_authenticate(manager)

        response = self.client.get("/api/v1/reports/overview")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["departments"], 1)
        self.assertEqual(response.json()["programs"], 1)