from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import Student
from tests.helpers import create_role_user


class SprintOneAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.campus = Campus.objects.create(name="Main", code="MAIN")
        self.unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department_a = Department.objects.create(
            unit=self.unit, campus=self.campus, name="Travel", code="TRV"
        )
        self.department_b = Department.objects.create(
            unit=self.unit, campus=self.campus, name="Hospitality", code="HSP"
        )
        self.users = {
            role: create_role_user(f"uid-{role}", role=role) for role in Role.values
        }
        Student.objects.create(
            user=self.users[Role.STUDENT],
            department=self.department_a,
            registration_number="TRV-2026-0098",
            first_name="Student",
            last_name="User",
            email="student@example.test",
            admission_year=2026,
        )
        RoleScope.objects.create(
            user=self.users[Role.HOD], department=self.department_a
        )
        self.scoped_teacher = create_role_user("scoped-teacher", role=Role.TEACHER)
        self.other_teacher = create_role_user("other-teacher", role=Role.TEACHER)
        RoleScope.objects.create(user=self.scoped_teacher, department=self.department_a)
        RoleScope.objects.create(user=self.other_teacher, department=self.department_b)

    def test_user_listing_role_matrix(self):
        expected = {
            Role.SUPER_ADMIN: 200,
            Role.ADMIN: 200,
            Role.DIRECTOR: 200,
            Role.HOD: 200,
            Role.TEACHER: 403,
            Role.BURSAR: 403,
            Role.STUDENT: 403,
        }
        for role, status_code in expected.items():
            with self.subTest(role=role):
                self.client.force_authenticate(self.users[role])
                response = self.client.get("/api/v1/users/")
                self.assertEqual(response.status_code, status_code)
                if role == Role.HOD:
                    self.assertEqual(
                        {item["id"] for item in response.json()["results"]},
                        {
                            str(self.users[Role.HOD].id),
                            str(self.scoped_teacher.id),
                        },
                    )

    def test_department_rows_are_scoped_by_hod_department(self):
        self.client.force_authenticate(self.users[Role.HOD])
        response = self.client.get("/api/v1/departments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(self.department_a.id)],
        )

    def test_non_management_role_cannot_list_departments(self):
        for role in (Role.TEACHER, Role.BURSAR, Role.STUDENT):
            with self.subTest(role=role):
                self.client.force_authenticate(self.users[role])
                self.assertEqual(
                    self.client.get("/api/v1/departments/").status_code, 403
                )

    def test_unapproved_user_is_restricted_to_profile_access(self):
        user = User.objects.create_user("awaiting-approval")
        self.client.force_authenticate(user)
        self.assertEqual(self.client.get("/api/v1/me").status_code, 200)
        self.assertEqual(self.client.get("/api/v1/users/").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/departments/").status_code, 403)

    def test_director_and_hod_cannot_change_department_data(self):
        for role in (Role.DIRECTOR, Role.HOD):
            with self.subTest(role=role):
                self.client.force_authenticate(self.users[role])
                response = self.client.post(
                    "/api/v1/departments/",
                    {"unit": str(self.unit.id), "name": "New", "code": "NEW"},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)

    def test_admin_can_create_department_and_change_is_audited(self):
        self.client.force_authenticate(self.users[Role.ADMIN])
        response = self.client.post(
            "/api/v1/departments/",
            {
                "unit": str(self.unit.id),
                "name": "New department",
                "code": "NEW",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertIn("id", response.json())
        self.assertTrue(AuditLog.objects.filter(action="created").exists())

    def test_admin_cannot_promote_user_to_admin(self):
        self.client.force_authenticate(self.users[Role.ADMIN])
        response = self.client.patch(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/role/",
            {"role": Role.ADMIN},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.users[Role.TEACHER].role, Role.TEACHER)

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-SUPER_ADMIN"},
    )
    def test_super_admin_role_change_is_revocation_checked_and_audited(
        self, verify_token, ensure_firebase
    ):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        response = self.client.patch(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/role/",
            {"role": Role.BURSAR},
            format="json",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )
        self.assertEqual(response.status_code, 200)
        verify_token.assert_called_once_with("verified-token", check_revoked=True)
        self.users[Role.TEACHER].refresh_from_db()
        self.assertEqual(self.users[Role.TEACHER].role, Role.BURSAR)
        audit = AuditLog.objects.get(action="role_changed")
        self.assertEqual(audit.before["role"], Role.TEACHER)
        self.assertEqual(audit.after["role"], Role.BURSAR)

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-ADMIN"},
    )
    @patch(
        "apps.accounts.views.fb_auth.create_user",
        return_value=SimpleNamespace(uid="invited-user"),
    )
    def test_admin_invite_creates_local_user_and_audit_record(
        self, create_firebase_user, verify_token, ensure_firebase
    ):
        self.client.force_authenticate(self.users[Role.ADMIN])
        response = self.client.post(
            "/api/v1/users/invite/",
            {
                "email": "new.bursar@example.com",
                "display_name": "New Bursar",
                "role": Role.BURSAR,
            },
            format="json",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )
        self.assertEqual(response.status_code, 201)
        invited_user = User.objects.get(firebase_uid="invited-user")
        self.assertTrue(
            RoleAssignment.objects.filter(
                user=invited_user, role=Role.BURSAR, unit__isnull=True
            ).exists()
        )
        self.assertTrue(AuditLog.objects.filter(action="invited").exists())

    def test_hod_invite_requires_department_scopes(self):
        self.client.force_authenticate(self.users[Role.ADMIN])
        response = self.client.post(
            "/api/v1/users/invite/",
            {
                "email": "new.hod@example.com",
                "display_name": "New HOD",
                "role": Role.HOD,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("department_ids", response.json()["fields"])
