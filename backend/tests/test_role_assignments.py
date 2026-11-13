from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.accounts.models import RoleAssignment, RoleScope, User
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

    def test_role_helpers_match_active_global_and_unit_assignments(self):
        wti = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind="ACADEMIC"
        )
        wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Training Academy", kind="ACADEMIC"
        )
        user = User.objects.create_user("scoped-role-user")
        RoleAssignment.objects.create(user=user, role=Role.ADMIN)
        RoleAssignment.objects.create(user=user, role=Role.TEACHER, unit=wti)
        RoleAssignment.objects.create(user=user, role=Role.CASHIER, unit=wta)
        RoleAssignment.objects.create(
            user=user, role=Role.CASHIER, unit=wti, is_active=False
        )
        user.clear_role_cache()

        self.assertTrue(user.has_role_global(Role.ADMIN))
        self.assertFalse(user.has_role_global(Role.TEACHER))
        self.assertTrue(user.has_role_for_unit(Role.TEACHER, wti.id))
        self.assertFalse(user.has_role_for_unit(Role.TEACHER, wta.id))
        self.assertFalse(user.has_role_for_unit(Role.CASHIER, wti.id))
        self.assertFalse(user.has_role_for_unit(Role.ADMIN, wti.id))
        self.assertEqual(
            user.unit_ids_for(Role.TEACHER, Role.CASHIER),
            tuple(sorted((wti.id, wta.id), key=str)),
        )
        self.assertEqual(user.unit_ids_for(Role.HOD), ())

    def test_group_bursar_is_global_but_not_an_assignment_to_a_specific_unit(self):
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind="ACADEMIC"
        )
        user = User.objects.create_user("group-bursar")
        RoleAssignment.objects.create(user=user, role=Role.BURSAR)
        user.clear_role_cache()

        self.assertTrue(user.has_role_global(Role.BURSAR))
        self.assertFalse(user.has_role_for_unit(Role.BURSAR, unit.id))
        self.assertEqual(user.unit_ids_for(Role.BURSAR), ())

    def test_hod_department_ids_require_active_hod_unit_assignment(self):
        wti = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind="ACADEMIC"
        )
        wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Training Academy", kind="ACADEMIC"
        )
        campus = Campus.objects.create(name="Main", code="MAIN")
        wti_department = Department.objects.create(
            unit=wti, campus=campus, name="Travel", code="TRV"
        )
        wta_department = Department.objects.create(
            unit=wta, campus=campus, name="Business", code="BUS"
        )
        user = User.objects.create_user("scoped-hod")
        RoleAssignment.objects.create(user=user, role=Role.HOD, unit=wti)
        RoleAssignment.objects.create(
            user=user, role=Role.HOD, unit=wta, is_active=False
        )
        RoleScope.objects.create(user=user, department=wti_department)
        RoleScope.objects.create(user=user, department=wta_department)
        user.clear_role_cache()

        self.assertEqual(user.department_ids_for_hod(), (wti_department.id,))

        active_assignment = user.assignments.get(role=Role.HOD, unit=wti)
        active_assignment.is_active = False
        active_assignment.save(update_fields=("is_active",))
        user.clear_role_cache()
        self.assertEqual(user.department_ids_for_hod(), ())

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
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        department = Department.objects.create(
            unit=unit, campus=campus, name="Travel", code="TRV"
        )
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
