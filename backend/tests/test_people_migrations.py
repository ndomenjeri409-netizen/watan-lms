from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class StudentHomeUnitMigrationTests(TransactionTestCase):
    migrate_from = (
        "people",
        "0006_student_account_status_alter_student_email_and_more",
    )
    migrate_to = ("people", "0007_d9_student_registration")

    def setUp(self):
        super().setUp()
        self.student_id = None
        self.migration_failed = False
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        self.BusinessUnit = old_apps.get_model("org", "BusinessUnit")
        self.Department = old_apps.get_model("org", "Department")
        self.Student = old_apps.get_model("people", "Student")
        self.unit = self.BusinessUnit.objects.create(
            code="MIGWTI",
            name="Migration Institute",
            kind="ACADEMIC",
        )
        self.department = self.Department.objects.create(
            unit=self.unit,
            name="Migration Department",
            code="MIGINS",
        )

    def tearDown(self):
        executor = MigrationExecutor(connection)
        if self.migration_failed:
            old_apps = executor.loader.project_state([self.migrate_from]).apps
            old_apps.get_model("people", "Student").objects.filter(
                pk=self.student_id
            ).delete()
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def create_student(self, registration_number):
        student = self.Student.objects.create(
            department=self.department,
            registration_number=registration_number,
            first_name="Migration",
            last_name="Student",
            admission_year=2026,
        )
        self.student_id = student.pk
        return student

    def test_backfills_recognized_prefix_and_department_fallback(self):
        prefixed = self.create_student("MIGWTI/MIGINS/2026/0001")
        fallback = self.create_student("MIGINS-2026-0001")

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        apps = executor.loader.project_state([self.migrate_to]).apps
        Student = apps.get_model("people", "Student")

        self.assertEqual(Student.objects.get(pk=prefixed.pk).home_unit_id, self.unit.pk)
        self.assertEqual(Student.objects.get(pk=fallback.pk).home_unit_id, self.unit.pk)

    def test_unrecognized_unit_prefix_fails_with_student_details(self):
        student = self.create_student("UNKNOWN/MIGINS/2026/0001")

        executor = MigrationExecutor(connection)
        with self.assertRaisesRegex(
            RuntimeError,
            f"student={student.pk}, registration_number=UNKNOWN/MIGINS/2026/0001",
        ):
            executor.migrate([self.migrate_to])
        self.migration_failed = True
