import csv
from datetime import date, time
from importlib import import_module
from pathlib import Path

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from apps.academics.models import Course
from apps.academics.serializers import CourseSerializer
from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.enrollment.models import Enrollment
from apps.enrollment.serializers import EnrollmentSerializer
from apps.org.models import BusinessUnit, Department, Program
from apps.org.serializers import ProgramSerializer
from apps.people.models import Student
from apps.scheduling.models import ClassGroup, TimetableSlot
from apps.scheduling.serializers import TimetableSlotSerializer
from tests.helpers import postgres_only


class UnitOwnershipTests(TestCase):
    def setUp(self):
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
        self.admin = User.objects.create_user("unit-owner-admin", role=Role.ADMIN)
        self.manager_a = User.objects.create_user(
            "unit-owner-manager", role=Role.UNIT_MANAGER, unit=self.unit_a
        )
        self.hod_a = User.objects.create_user(
            "unit-owner-hod", role=Role.HOD, unit=self.unit_a
        )
        RoleScope.objects.create(user=self.hod_a, department=self.department_a)
        self.teacher_a = User.objects.create_user(
            "unit-owner-teacher-a", role=Role.TEACHER, unit=self.unit_a
        )
        self.student_user = User.objects.create_user("unit-owner-student")
        self.student = Student.objects.create(
            user=self.student_user,
            department=self.department_a,
            registration_number="INS-2026-0001",
            first_name="Student",
            last_name="One",
            email="unit-owner-student@example.test",
            admission_year=2026,
        )
        self.program_a = Program.objects.create(
            department=self.department_a, name="Institute Program", code="INS-P"
        )
        self.program_b = Program.objects.create(
            department=self.department_b, name="Travel Program", code="TRV-P"
        )
        self.course_a = Course.objects.create(
            department=self.department_a,
            program=self.program_a,
            created_by=self.admin,
            title="Institute Course",
            code="INS-C",
        )
        self.course_b = Course.objects.create(
            department=self.department_b,
            program=self.program_b,
            created_by=self.admin,
            title="Travel Course",
            code="TRV-C",
        )
        self.class_group = ClassGroup.objects.create(
            course=self.course_a,
            name="Institute Group",
            code="INS-G",
        )
        self.enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course_a,
            class_group=self.class_group,
            status=Enrollment.Status.ACTIVE,
        )
        self.slot = TimetableSlot.objects.create(
            class_group=self.class_group,
            weekday=0,
            starts_at=time(9),
            ends_at=time(10),
            effective_from=date(2026, 1, 1),
        )

    def test_child_units_are_derived_from_their_parent(self):
        self.assertEqual(self.program_a.unit_id, self.unit_a.id)
        self.assertEqual(self.course_a.unit_id, self.unit_a.id)
        self.assertEqual(self.enrollment.unit_id, self.unit_a.id)
        self.assertEqual(self.slot.unit_id, self.unit_a.id)

    def test_public_mapping_matches_the_data_migration(self):
        root = Path(__file__).resolve().parents[2]
        with (root / "docs" / "department_unit_map.csv").open(
            newline="", encoding="utf-8"
        ) as mapping_file:
            mapping = {
                row["department_code"]: row["unit_code"]
                for row in csv.DictReader(mapping_file)
            }
        migration = import_module("apps.org.migrations.0006_a4_unit_ownership")

        self.assertEqual(mapping, migration.DEPARTMENT_UNIT_MAP)

    def test_data_migration_fails_on_an_unmapped_department(self):
        Department.objects.create(
            unit=self.unit_a, name="Unmapped Department", code="UNM"
        )
        migration = import_module("apps.org.migrations.0006_a4_unit_ownership")

        with self.assertRaisesRegex(RuntimeError, "UNM"):
            migration.assign_units(apps, None)

    def test_child_serializers_expose_unit_as_read_only(self):
        for serializer_class in (
            ProgramSerializer,
            CourseSerializer,
            EnrollmentSerializer,
            TimetableSlotSerializer,
        ):
            with self.subTest(serializer=serializer_class.__name__):
                self.assertTrue(serializer_class().fields["unit"].read_only)

    def test_direct_unit_querysets_enforce_unit_and_department_scope(self):
        self.assertEqual(
            set(Program.objects.for_user(self.manager_a).values_list("pk", flat=True)),
            {self.program_a.pk},
        )
        self.assertEqual(
            set(Course.objects.for_user(self.manager_a).values_list("pk", flat=True)),
            {self.course_a.pk},
        )
        self.assertEqual(
            set(Enrollment.objects.for_user(self.hod_a).values_list("pk", flat=True)),
            {self.enrollment.pk},
        )
        self.assertEqual(
            set(
                TimetableSlot.objects.for_user(self.hod_a).values_list("pk", flat=True)
            ),
            {self.slot.pk},
        )

    def test_model_saves_reject_parent_unit_mismatches(self):
        with self.assertRaises(ValidationError):
            Program(
                unit=self.unit_b,
                department=self.department_a,
                name="Invalid Program",
                code="BAD-P",
            ).save()

        with self.assertRaises(ValidationError):
            Course(
                unit=self.unit_b,
                department=self.department_a,
                created_by=self.admin,
                title="Invalid Course",
                code="BAD-C",
            ).save()

        with self.assertRaises(ValidationError):
            Enrollment(
                unit=self.unit_b,
                student=self.student,
                course=self.course_a,
            ).save()

        with self.assertRaises(ValidationError):
            TimetableSlot(
                unit=self.unit_b,
                class_group=self.class_group,
                weekday=1,
                starts_at=time(9),
                ends_at=time(10),
                effective_from=date(2026, 1, 1),
            ).save()

    def test_parent_unit_changes_cannot_invalidate_existing_children(self):
        self.department_a.unit = self.unit_b
        with self.assertRaises(ValidationError):
            self.department_a.save()
        self.department_a.refresh_from_db()

        self.program_a.department = self.department_b
        self.program_a.unit = self.unit_b
        with self.assertRaises(ValidationError):
            self.program_a.save()
        self.program_a.refresh_from_db()

    @postgres_only
    def test_database_guards_reject_parent_unit_mismatches(self):
        updates = (
            lambda: Program.objects.filter(pk=self.program_a.pk).update(
                unit=self.unit_b
            ),
            lambda: Course.objects.filter(pk=self.course_a.pk).update(unit=self.unit_b),
            lambda: Enrollment.objects.filter(pk=self.enrollment.pk).update(
                unit=self.unit_b
            ),
            lambda: TimetableSlot.objects.filter(pk=self.slot.pk).update(
                unit=self.unit_b
            ),
            lambda: Department.objects.filter(pk=self.department_a.pk).update(
                unit=self.unit_b
            ),
        )
        for update in updates:
            with (
                self.subTest(update=update),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
            ):
                update()
