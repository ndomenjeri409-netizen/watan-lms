from datetime import date

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.org.models import (
    AcademicPeriod,
    BusinessUnit,
    Campus,
    Department,
    Program,
)


class OrganizationRoleAssignmentAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.campus_a = Campus.objects.create(name="Campus A", code="CAMP-A")
        self.campus_b = Campus.objects.create(name="Campus B", code="CAMP-B")
        self.campus_outside = Campus.objects.create(
            name="Campus Outside", code="CAMP-X"
        )
        self.wti = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        self.wds = BusinessUnit.objects.create(
            code="WDS", name="Watan Driving School", kind=BusinessUnit.Kind.DRIVING
        )
        self.hod_department = Department.objects.create(
            unit=self.wti, campus=self.campus_a, name="Travel", code="TRV"
        )
        self.other_wti_department = Department.objects.create(
            unit=self.wti, campus=self.campus_outside, name="Business", code="BUS"
        )
        self.manager_department = Department.objects.create(
            unit=self.wta, campus=self.campus_b, name="Agency", code="AGY"
        )
        self.teacher_department = Department.objects.create(
            unit=self.wds,
            campus=self.campus_outside,
            name="Driving",
            code="DRV",
        )
        self.hod_program = Program.objects.create(
            department=self.hod_department, name="Travel Studies", code="TRV-P"
        )
        self.other_wti_program = Program.objects.create(
            department=self.other_wti_department,
            name="Business Studies",
            code="BUS-P",
        )
        self.manager_program = Program.objects.create(
            department=self.manager_department, name="Agency Studies", code="AGY-P"
        )
        self.teacher_program = Program.objects.create(
            department=self.teacher_department,
            name="Driving Studies",
            code="DRV-P",
        )
        self.period = AcademicPeriod.objects.create(
            name="2026 Intake",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.INTAKE,
        )
        self.multi_role_user = User.objects.create_user("org-hod-manager-teacher")
        RoleAssignment.objects.create(
            user=self.multi_role_user, role=Role.HOD, unit=self.wti
        )
        RoleAssignment.objects.create(
            user=self.multi_role_user, role=Role.UNIT_MANAGER, unit=self.wta
        )
        RoleAssignment.objects.create(
            user=self.multi_role_user, role=Role.TEACHER, unit=self.wds
        )
        RoleScope.objects.create(
            user=self.multi_role_user, department=self.hod_department
        )

    def test_multi_role_scopes_union_hod_and_manager_but_not_teacher_unit(self):
        self.assertEqual(
            set(
                Department.objects.for_user(self.multi_role_user).values_list(
                    "id", flat=True
                )
            ),
            {self.hod_department.id, self.manager_department.id},
        )
        self.assertEqual(
            set(
                Program.objects.for_user(self.multi_role_user).values_list(
                    "id", flat=True
                )
            ),
            {self.hod_program.id, self.manager_program.id},
        )
        self.assertEqual(
            set(
                Campus.objects.for_user(self.multi_role_user).values_list(
                    "id", flat=True
                )
            ),
            {self.campus_a.id, self.campus_b.id},
        )

        wti_period = AcademicPeriod.objects.create(
            name="WTI Role Term",
            starts_on=date(2027, 1, 1),
            ends_on=date(2027, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
            unit=self.wti,
        )
        wta_period = AcademicPeriod.objects.create(
            name="WTA Role Intake",
            starts_on=date(2027, 1, 1),
            ends_on=date(2027, 12, 31),
            kind=AcademicPeriod.Kind.INTAKE,
            unit=self.wta,
        )
        AcademicPeriod.objects.create(
            name="WDS Teacher Term",
            starts_on=date(2027, 1, 1),
            ends_on=date(2027, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
            unit=self.wds,
        )
        self.client.force_authenticate(self.multi_role_user)
        for path, expected_ids in (
            (
                "/api/v1/departments/",
                {str(self.hod_department.id), str(self.manager_department.id)},
            ),
            (
                "/api/v1/programs/",
                {str(self.hod_program.id), str(self.manager_program.id)},
            ),
            (
                "/api/v1/campuses/",
                {str(self.campus_a.id), str(self.campus_b.id)},
            ),
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200, response.content)
                self.assertEqual(
                    {item["id"] for item in response.json()["results"]}, expected_ids
                )

        response = self.client.get("/api/v1/academic-periods/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 3)
        self.assertEqual(
            {item["name"] for item in response.json()["results"]},
            {self.period.name, wti_period.name, wta_period.name},
        )

    def test_director_and_auditor_are_global_read_only_org_users(self):
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = User.objects.create_user(f"org-{role.lower()}", role=role)
            self.client.force_authenticate(user)

            response = self.client.get("/api/v1/departments/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 4)

            response = self.client.get("/api/v1/campuses/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 3)

            response = self.client.get("/api/v1/academic-periods/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["count"], 1)

            response = self.client.post(
                "/api/v1/departments/",
                {
                    "unit": str(self.wti.id),
                    "name": f"Forbidden {role}",
                    "code": f"F{role[:3]}",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 403)

    def test_unit_manager_can_read_group_and_own_unit_periods(self):
        legacy_period = AcademicPeriod.objects.create(
            name="Legacy Group Period",
            starts_on=date(2025, 1, 1),
            ends_on=date(2025, 12, 31),
        )
        wta_period = AcademicPeriod.objects.create(
            name="WTA Intake",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.INTAKE,
            unit=self.wta,
        )
        AcademicPeriod.objects.create(
            name="WTI Term",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
            unit=self.wti,
        )
        manager = User.objects.create_user(
            "org-manager", role=Role.UNIT_MANAGER, unit=self.wta
        )
        self.client.force_authenticate(manager)

        response = self.client.get("/api/v1/academic-periods/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["count"], 3)
        self.assertEqual(
            {item["name"] for item in response.json()["results"]},
            {self.period.name, legacy_period.name, wta_period.name},
        )
        self.assertIsNone(
            next(
                item["kind"]
                for item in response.json()["results"]
                if item["name"] == legacy_period.name
            )
        )

    def test_academic_period_creation_requires_kind_and_accepts_unit(self):
        admin = User.objects.create_user("org-admin", role=Role.ADMIN)
        self.client.force_authenticate(admin)
        payload = {
            "name": "WTA 2027 Intake",
            "starts_on": "2027-01-01",
            "ends_on": "2027-12-31",
            "kind": AcademicPeriod.Kind.INTAKE,
            "unit": str(self.wta.id),
            "is_current": False,
            "is_active": True,
        }

        response = self.client.post("/api/v1/academic-periods/", payload, format="json")

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["kind"], AcademicPeriod.Kind.INTAKE)
        self.assertEqual(response.json()["unit"], str(self.wta.id))

        missing_kind = {**payload, "name": "Missing Type"}
        del missing_kind["kind"]
        response = self.client.post(
            "/api/v1/academic-periods/", missing_kind, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("kind", response.json()["fields"])

        null_kind = {**payload, "name": "Null Type", "kind": None}
        response = self.client.post(
            "/api/v1/academic-periods/", null_kind, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("kind", response.json()["fields"])
