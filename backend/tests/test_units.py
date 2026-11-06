from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit
from tests.helpers import create_role_user

EXPECTED_UNIT_CODES = ("HQ", "WCY", "WDS", "WTA", "WTI")


class BusinessUnitTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_seed_units_is_idempotent_and_matches_documented_units(self):
        call_command("seed_units", stdout=StringIO())
        call_command("seed_units", stdout=StringIO())

        self.assertEqual(
            tuple(BusinessUnit.objects.values_list("code", flat=True)),
            EXPECTED_UNIT_CODES,
        )
        self.assertEqual(BusinessUnit.objects.count(), len(EXPECTED_UNIT_CODES))
        wcy = BusinessUnit.objects.get(code="WCY")
        self.assertEqual(wcy.kind, BusinessUnit.Kind.SERVICES)
        self.assertTrue(wcy.modules["finance"])

    def test_group_roles_can_list_active_units(self):
        call_command("seed_units", stdout=StringIO())
        BusinessUnit.objects.create(
            code="OLD",
            name="Inactive unit",
            kind=BusinessUnit.Kind.GROUP,
            is_active=False,
        )

        for role in (Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.BURSAR):
            with self.subTest(role=role):
                user = User.objects.create_user(f"uid-{role}", role=role)
                self.client.force_authenticate(user)

                response = self.client.get("/api/v1/units")

                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    {unit["code"] for unit in response.json()["results"]},
                    set(EXPECTED_UNIT_CODES),
                )

    def test_unit_roles_only_receive_their_assigned_units(self):
        call_command("seed_units", stdout=StringIO())
        user = create_role_user("teacher", role=Role.TEACHER)
        self.client.force_authenticate(user)

        response = self.client.get("/api/v1/units")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([unit["code"] for unit in response.json()["results"]], ["WTI"])

    def test_units_require_authentication(self):
        response = self.client.get("/api/v1/units")
        self.assertEqual(response.status_code, 401)
