from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import RoleAssignment, User
from apps.accounts.roles import Role
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import Student


class RoleAssignmentTests(TestCase):
    def test_user_helpers_include_multiple_assignments_and_units(self):
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind="ACADEMIC"
        )
        user = User.objects.create_user("multi-role-user")
        RoleAssignment.objects.create(user=user, role=Role.ADMIN)
        RoleAssignment.objects.create(user=user, role=Role.TEACHER, unit=unit)
        user.clear_role_cache()

        self.assertEqual(user.roles(), {Role.ADMIN, Role.TEACHER})
        self.assertTrue(user.has_role(Role.ADMIN, Role.TEACHER))
        self.assertTrue(user.has_global_read())
        self.assertEqual(user.unit_ids(), (unit.id,))

    def test_unit_scoped_roles_require_a_unit(self):
        user = User.objects.create_user("invalid-assignment-user")
        assignment = RoleAssignment(user=user, role=Role.TEACHER)

        with self.assertRaises(ValidationError):
            assignment.full_clean()

    def test_database_rejects_invalid_scope_and_duplicate_assignments(self):
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind="ACADEMIC"
        )
        user = User.objects.create_user("constraint-user")
        RoleAssignment.objects.create(user=user, role=Role.ADMIN)
        RoleAssignment.objects.create(user=user, role=Role.TEACHER, unit=unit)

        invalid_assignments = (
            RoleAssignment(user=user, role=Role.ADMIN, unit=unit),
            RoleAssignment(user=user, role=Role.TEACHER),
            RoleAssignment(user=user, role=Role.ADMIN),
            RoleAssignment(user=user, role=Role.TEACHER, unit=unit),
        )
        for assignment in invalid_assignments:
            with (
                self.subTest(role=assignment.role, unit=assignment.unit_id),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                assignment.save()

    def test_student_role_is_derived_from_student_record(self):
        user = User.objects.create_user("student-user")
        campus = Campus.objects.create(name="Main", code="MAIN")
        department = Department.objects.create(campus=campus, name="Travel", code="TRV")
        Student.objects.create(
            user=user,
            department=department,
            registration_number="TRV-2026-0099",
            first_name="Amina",
            last_name="Njeri",
            email="amina@example.test",
            admission_year=2026,
        )

        self.assertTrue(user.has_role(Role.STUDENT))
        self.assertEqual(user.roles(), {Role.STUDENT})
