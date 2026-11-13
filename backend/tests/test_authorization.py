from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
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
            Role.UNIT_MANAGER: 200,
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

    def test_multi_role_user_list_combines_only_assigned_scopes(self):
        manager_unit = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        teacher_unit = BusinessUnit.objects.create(
            code="WDS", name="Watan Digital Services", kind=BusinessUnit.Kind.TRAINING
        )
        manager = self.users[Role.HOD]
        RoleAssignment.objects.create(
            user=manager, role=Role.UNIT_MANAGER, unit=manager_unit
        )
        RoleAssignment.objects.create(
            user=manager, role=Role.TEACHER, unit=teacher_unit
        )
        manager_unit_user = create_role_user(
            "manager-unit-user", role=Role.CASHIER, unit=manager_unit
        )
        teacher_unit_user = create_role_user(
            "teacher-unit-user", role=Role.TEACHER, unit=teacher_unit
        )
        self.client.force_authenticate(manager)

        response = self.client.get("/api/v1/users/")

        self.assertEqual(response.status_code, 200)
        visible_ids = {item["id"] for item in response.json()["results"]}
        self.assertEqual(
            visible_ids,
            {
                str(manager.id),
                str(self.scoped_teacher.id),
                str(manager_unit_user.id),
            },
        )
        self.assertNotIn(str(self.other_teacher.id), visible_ids)
        self.assertNotIn(str(teacher_unit_user.id), visible_ids)

    def test_user_list_reports_assignments_and_pending_status(self):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        response = self.client.get("/api/v1/users/")
        self.assertEqual(response.status_code, 200)
        rows = {row["id"]: row for row in response.json()["results"]}

        super_admin = rows[str(self.users[Role.SUPER_ADMIN].id)]
        self.assertEqual(super_admin["status"], "ACTIVE")
        self.assertEqual(super_admin["assignments"][0]["role"], Role.SUPER_ADMIN)
        self.assertIsNone(super_admin["assignments"][0]["unit"])

        pending = User.objects.create_user("pending-user")
        response = self.client.get("/api/v1/users/")
        pending_row = next(
            row for row in response.json()["results"] if row["id"] == str(pending.id)
        )
        self.assertEqual(pending_row["status"], "PENDING")
        self.assertEqual(pending_row["assignments"], [])

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
        for role in (Role.SUPER_ADMIN, Role.ADMIN):
            with self.subTest(role=role):
                response = self.client.post(
                    f"/api/v1/users/{self.users[Role.TEACHER].id}/assignments/",
                    {"role": role},
                    format="json",
                )
                self.assertEqual(response.status_code, 403)
        self.assertFalse(
            self.users[Role.TEACHER]
            .assignments.filter(role__in=(Role.SUPER_ADMIN, Role.ADMIN))
            .exists()
        )

    def test_assignment_requires_unit_for_unit_roles_and_rejects_it_for_group_roles(
        self,
    ):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        response = self.client.post(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/assignments/",
            {"role": Role.CASHIER},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["fields"]["unit"],
            ["A business unit is required for this role."],
        )
        self.assertEqual(
            response.json()["message"], "A business unit is required for this role."
        )

        response = self.client.post(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/assignments/",
            {"role": Role.ADMIN, "unit": str(self.unit.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("unit", response.json()["fields"])

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-SUPER_ADMIN"},
    )
    def test_super_admin_assignment_is_revocation_checked_and_audited(
        self, verify_token, ensure_firebase
    ):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        response = self.client.post(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/assignments/",
            {"role": Role.BURSAR},
            format="json",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )
        self.assertEqual(response.status_code, 201)
        verify_token.assert_called_once_with("verified-token", check_revoked=True)
        self.assertTrue(
            self.users[Role.TEACHER]
            .assignments.filter(role=Role.BURSAR, unit__isnull=True, is_active=True)
            .exists()
        )
        audit = AuditLog.objects.get(action="assignment_changed")
        self.assertIsNone(audit.unit)
        self.assertEqual(audit.scope, AuditLog.Scope.GROUP)
        self.assertEqual(audit.actor, self.users[Role.SUPER_ADMIN])
        self.assertEqual(audit.after["role"], Role.BURSAR)

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-SUPER_ADMIN"},
    )
    def test_assignment_audit_records_the_assigned_unit(
        self, verify_token, ensure_firebase
    ):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        response = self.client.post(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/assignments/",
            {"role": Role.CASHIER, "unit": str(self.unit.id)},
            format="json",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )
        self.assertEqual(response.status_code, 201)
        audit = AuditLog.objects.get(action="assignment_changed")
        self.assertEqual(audit.unit, self.unit)
        self.assertEqual(audit.scope, AuditLog.Scope.UNIT)
        self.assertEqual(audit.actor, self.users[Role.SUPER_ADMIN])
        verify_token.assert_called_once_with("verified-token", check_revoked=True)

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-SUPER_ADMIN"},
    )
    def test_super_admin_cannot_remove_own_assignment(
        self, verify_token, ensure_firebase
    ):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        assignment = self.users[Role.SUPER_ADMIN].assignments.get(role=Role.SUPER_ADMIN)
        response = self.client.delete(
            f"/api/v1/users/{self.users[Role.SUPER_ADMIN].id}/assignments/{assignment.id}/",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            RoleAssignment.objects.filter(pk=assignment.pk, is_active=True).exists()
        )

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-SUPER_ADMIN"},
    )
    def test_assignment_deletion_deactivates_and_audits_row(
        self, verify_token, ensure_firebase
    ):
        self.client.force_authenticate(self.users[Role.SUPER_ADMIN])
        assignment = self.users[Role.TEACHER].assignments.get(role=Role.TEACHER)
        response = self.client.delete(
            f"/api/v1/users/{self.users[Role.TEACHER].id}/assignments/{assignment.id}/",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )

        self.assertEqual(response.status_code, 200)
        assignment.refresh_from_db()
        self.assertFalse(assignment.is_active)
        self.assertTrue(RoleAssignment.objects.filter(pk=assignment.pk).exists())
        audit = AuditLog.objects.get(action="assignment_deactivated")
        self.assertEqual(audit.unit, self.unit)
        self.assertEqual(audit.actor, self.users[Role.SUPER_ADMIN])
        self.assertFalse(audit.after["is_active"])

    def test_report_pending_users_shows_audit_role_without_assigning(self):
        pending = User.objects.create_user(
            "pending-report",
            email="pending@example.test",
            display_name="Pending User",
        )
        AuditLog.objects.create(
            actor=self.users[Role.SUPER_ADMIN],
            scope=AuditLog.Scope.GROUP,
            actor_kind=AuditLog.ActorKind.USER,
            action="role_changed",
            object_type="accounts.User",
            object_id=str(pending.pk),
            after={"role": Role.HOD},
        )
        output = StringIO()

        call_command("report_pending_users", stdout=output)

        self.assertIn("pending@example.test", output.getvalue())
        self.assertIn("Pending User", output.getvalue())
        self.assertIn(Role.HOD, output.getvalue())
        self.assertIn("No unit was inferred.", output.getvalue())
        self.assertFalse(pending.assignments.filter(is_active=True).exists())

    @patch("apps.accounts.views.authentication._ensure_firebase")
    @patch(
        "apps.accounts.views.fb_auth.verify_id_token",
        return_value={"uid": "uid-SUPER_ADMIN"},
    )
    def test_last_active_super_admin_assignment_cannot_be_removed(
        self, verify_token, ensure_firebase
    ):
        actor = self.users[Role.SUPER_ADMIN]
        actor.roles()
        RoleAssignment.objects.filter(
            user=actor,
            role=Role.SUPER_ADMIN,
        ).update(is_active=False)
        last_admin = create_role_user("last-super-admin", role=Role.SUPER_ADMIN)
        assignment = last_admin.assignments.get(role=Role.SUPER_ADMIN)
        self.client.force_authenticate(actor)

        response = self.client.delete(
            f"/api/v1/users/{last_admin.id}/assignments/{assignment.id}/",
            HTTP_AUTHORIZATION="Bearer verified-token",
        )

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["message"],
            "The last active SUPER_ADMIN assignment cannot be removed.",
        )
        self.assertTrue(
            RoleAssignment.objects.filter(pk=assignment.pk, is_active=True).exists()
        )

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
