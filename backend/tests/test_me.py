from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.authentication import FirebaseAuthentication
from apps.accounts.models import RoleAssignment, User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import Student


class MeTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_header_is_unauthorized(self):
        response = self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 401)

    def test_patch_updates_only_profile_fields(self):
        user = User.objects.create_user(
            "u1", email="a@b.com", display_name="Old name", role="ADMIN"
        )
        self.client.force_authenticate(user)

        response = self.client.patch(
            "/api/v1/me",
            {"display_name": "New name", "phone_number": "+254700000000"},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["display_name"], "New name")
        self.assertEqual(response.json()["phone_number"], "+254700000000")
        user.refresh_from_db()
        self.assertEqual(user.role, "ADMIN")

    def test_patch_rejects_fields_that_are_not_profile_editable(self):
        user = User.objects.create_user("u1", role="ADMIN")
        self.client.force_authenticate(user)

        response = self.client.patch("/api/v1/me", {"role": "ADMIN"}, format="json")

        self.assertEqual(response.status_code, 400)
        user.refresh_from_db()
        self.assertEqual(user.role, "ADMIN")

    def test_me_includes_active_assignments_and_access_flags(self):
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        user = User.objects.create_user("multi-role-user")
        RoleAssignment.objects.create(user=user, role=Role.ADMIN)
        RoleAssignment.objects.create(user=user, role=Role.TEACHER, unit=unit)
        RoleAssignment.objects.create(
            user=user, role=Role.CASHIER, unit=unit, is_active=False
        )
        self.client.force_authenticate(user)

        response = self.client.get("/api/v1/me")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            {
                (
                    assignment["role"],
                    assignment["unit"]["code"] if assignment["unit"] else None,
                )
                for assignment in payload["assignments"]
            },
            {(Role.ADMIN, None), (Role.TEACHER, "WTI")},
        )
        self.assertTrue(payload["is_global_read"])
        self.assertFalse(payload["awaiting_approval"])

    def test_me_approval_status_is_derived_from_assignments_and_student_link(self):
        user = User.objects.create_user("awaiting-user")
        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/me")
        self.assertTrue(response.json()["awaiting_approval"])

        campus = Campus.objects.create(name="Main", code="MAIN")
        department = Department.objects.create(campus=campus, name="Travel", code="TRV")
        Student.objects.create(
            user=user,
            department=department,
            registration_number="TRV-2026-0096",
            first_name="Student",
            last_name="User",
            email="student@example.test",
            admission_year=2026,
        )
        user.clear_role_cache()

        response = self.client.get("/api/v1/me")

        self.assertFalse(response.json()["awaiting_approval"])
        self.assertFalse(response.json()["is_global_read"])

    @patch("apps.accounts.authentication._ensure_firebase")
    @patch(
        "apps.accounts.authentication.fb_auth.verify_id_token", side_effect=ValueError
    )
    def test_invalid_token_is_unauthorized(self, verify_id_token, ensure_firebase):
        response = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer invalid")
        self.assertEqual(response.status_code, 401)

    @patch("apps.accounts.authentication._ensure_firebase")
    @patch(
        "apps.accounts.authentication.fb_auth.verify_id_token",
        return_value={"uid": "u1", "email": "a@b.com"},
    )
    def test_valid_token_creates_user(self, verify_id_token, ensure_firebase):
        response = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer valid")
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(firebase_uid="u1")
        self.assertIsNone(user.role)
        self.assertEqual(response.json()["email"], "a@b.com")

    @patch("apps.accounts.authentication._ensure_firebase")
    @patch(
        "apps.accounts.authentication.fb_auth.verify_id_token",
        return_value={"uid": "inactive"},
    )
    def test_inactive_user_is_unauthorized(self, verify_id_token, ensure_firebase):
        User.objects.create_user("inactive", is_active=False)
        response = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer valid")
        self.assertEqual(response.status_code, 401)


class FirebaseAuthenticationTests(TestCase):
    def test_absent_header_does_not_initialize_firebase(self):
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        request = Request(APIRequestFactory().get("/"))
        with patch("apps.accounts.authentication._ensure_firebase") as ensure:
            self.assertIsNone(FirebaseAuthentication().authenticate(request))
            ensure.assert_not_called()
