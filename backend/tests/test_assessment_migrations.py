from datetime import UTC, datetime

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class EnrollmentGradeConversionMigrationTests(TransactionTestCase):
    migrate_from = (
        "assessment",
        "0002_assessmenttemplate_alter_assessment_options_and_more",
    )
    migrate_to = ("assessment", "0004_grade_history_conversion")

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        self.old_apps = executor.loader.project_state([self.migrate_from]).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def _create_legacy_rows(self, *, mismatch=False):
        BusinessUnit = self.old_apps.get_model("org", "BusinessUnit")
        Campus = self.old_apps.get_model("org", "Campus")
        Department = self.old_apps.get_model("org", "Department")
        User = self.old_apps.get_model("accounts", "User")
        Course = self.old_apps.get_model("academics", "Course")
        ClassGroup = self.old_apps.get_model("scheduling", "ClassGroup")
        AssessmentTemplate = self.old_apps.get_model("assessment", "AssessmentTemplate")
        Assessment = self.old_apps.get_model("assessment", "Assessment")
        StoredFile = self.old_apps.get_model("files", "StoredFile")
        Submission = self.old_apps.get_model("assessment", "Submission")
        Grade = self.old_apps.get_model("assessment", "Grade")
        GradeRevision = self.old_apps.get_model("assessment", "GradeRevision")

        unit = BusinessUnit.objects.create(
            code="MIG",
            name="Migration Unit",
            kind="ACADEMIC",
        )
        campus = Campus.objects.create(name="Migration Campus", code="MIG-C")
        department = Department.objects.create(
            unit=unit,
            campus=campus,
            name="Migration Department",
            code="MIG-D",
        )
        teacher = User.objects.create(
            firebase_uid="migration-teacher",
            password="not-a-login",
        )
        student_user = User.objects.create(
            firebase_uid="migration-student",
            password="not-a-login",
        )
        course = Course.objects.create(
            unit=unit,
            department=department,
            created_by=teacher,
            title="Migration Course",
            slug="migration-course",
            code="MIG-101",
            status="PUBLISHED",
        )
        class_group = ClassGroup.objects.create(
            course=course,
            name="Migration Class",
            code="MIG-101-A",
        )
        other_group = ClassGroup.objects.create(
            course=course,
            name="Other Migration Class",
            code="MIG-101-B",
        )
        from apps.people.models import Student

        student = Student.objects.create(
            user_id=student_user.pk,
            department_id=department.pk,
            registration_number="MIG-2026-0001",
            first_name="Migration",
            last_name="Student",
            email="migration@example.test",
            admission_year=2026,
            account_status="ACTIVE",
        )
        from apps.enrollment.models import Enrollment

        Enrollment.objects.create(
            unit_id=unit.pk,
            student_id=student.pk,
            course_id=course.pk,
            class_group_id=(other_group if mismatch else class_group).pk,
            status="ACTIVE",
        )
        template = AssessmentTemplate.objects.create(
            course=course,
            created_by=teacher,
            title="Migration Exam",
            instructions="",
            kind="EXAM",
            maximum_score="100.00",
        )
        assessment = Assessment.objects.create(
            template=template,
            class_group=class_group,
            status="PUBLISHED",
            weight="1.00",
        )

        submissions = []
        attempt_count = 1 if mismatch else 2
        for attempt in range(1, attempt_count + 1):
            stored_file = StoredFile.objects.create(
                purpose="submission",
                owner_user=student_user,
                object_key=f"migration/{attempt}.pdf",
                original_name=f"migration-{attempt}.pdf",
                content_type="application/pdf",
                size_bytes=100,
                status="READY",
            )
            submissions.append(
                Submission.objects.create(
                    assessment=assessment,
                    student_id=student.pk,
                    attempt_number=attempt,
                    file=stored_file,
                )
            )

        if mismatch:
            grade = Grade.objects.create(
                submission=submissions[0],
                score="80.00",
                feedback="",
                status="DRAFT",
                revision=1,
                graded_by=teacher,
            )
            return {"grade_ids": [grade.pk], "unit_id": unit.pk}

        approved_at = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)
        published_at = datetime(2026, 1, 6, 12, 0, tzinfo=UTC)
        first = Grade.objects.create(
            submission=submissions[0],
            score="80.00",
            feedback="Approved attempt.",
            status="PUBLISHED",
            revision=2,
            graded_by=teacher,
            approved_by=teacher,
            approved_at=approved_at,
            published_at=published_at,
        )
        GradeRevision.objects.create(
            grade=first,
            revision=1,
            score="70.00",
            feedback="Initial draft.",
            status="DRAFT",
            changed_by=teacher,
            change_note="Initial mark.",
        )
        GradeRevision.objects.create(
            grade=first,
            revision=2,
            score="80.00",
            feedback="Approved attempt.",
            status="PUBLISHED",
            changed_by=teacher,
            change_note="Published.",
        )
        second = Grade.objects.create(
            submission=submissions[1],
            score="25.00",
            feedback="Later draft.",
            status="DRAFT",
            revision=1,
            graded_by=teacher,
        )
        return {
            "approved_at": approved_at,
            "grade_ids": [first.pk, second.pk],
            "published_at": published_at,
            "unit_id": unit.pk,
        }

    def test_multiple_attempts_keep_approved_official_grade_and_later_draft(self):
        original = self._create_legacy_rows()
        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_to])
        apps = executor.loader.project_state([self.migrate_to]).apps
        Grade = apps.get_model("assessment", "Grade")
        GradeRevision = apps.get_model("assessment", "GradeRevision")
        LegacyGradeArchive = apps.get_model("assessment", "LegacyGradeArchive")
        AuditLog = apps.get_model("audit", "AuditLog")

        grade = Grade.objects.get(
            enrollment__student__registration_number="MIG-2026-0001"
        )
        self.assertEqual(Grade.objects.count(), 1)
        self.assertEqual(grade.status, "DRAFT")
        self.assertEqual(str(grade.score), "25.00")
        self.assertEqual(grade.official_revision.status, "PUBLISHED")
        self.assertEqual(str(grade.official_revision.score), "80.00")
        self.assertEqual(grade.official_revision.approved_by_id, grade.graded_by_id)
        self.assertEqual(grade.official_revision.approved_at, original["approved_at"])
        self.assertEqual(grade.official_revision.published_at, original["published_at"])
        self.assertEqual(
            list(
                GradeRevision.objects.filter(grade=grade)
                .order_by("revision")
                .values_list("status", flat=True)
            ),
            ["DRAFT", "APPROVED", "PUBLISHED", "DRAFT"],
        )
        self.assertEqual(
            set(LegacyGradeArchive.objects.values_list("legacy_grade_id", flat=True)),
            set(original["grade_ids"]),
        )
        audit = AuditLog.objects.get(action="grade_history_migrated")
        self.assertEqual(audit.unit_id, original["unit_id"])
        self.assertEqual(audit.after["grades_converted"], 2)

        executor = MigrationExecutor(connection)
        executor.migrate([self.migrate_from])
        old_apps = executor.loader.project_state([self.migrate_from]).apps
        LegacyGrade = old_apps.get_model("assessment", "Grade")
        restored = list(LegacyGrade.objects.order_by("submission__attempt_number"))
        self.assertEqual({row.pk for row in restored}, set(original["grade_ids"]))
        self.assertEqual([row.status for row in restored], ["PUBLISHED", "DRAFT"])
        self.assertEqual([str(row.score) for row in restored], ["80.00", "25.00"])
        self.assertEqual(restored[0].approved_at, original["approved_at"])
        self.assertEqual(restored[0].published_at, original["published_at"])

    def test_conversion_fails_with_offending_id_when_enrollment_mapping_is_missing(
        self,
    ):
        original = self._create_legacy_rows(mismatch=True)
        executor = MigrationExecutor(connection)
        with self.assertRaisesRegex(RuntimeError, str(original["grade_ids"][0])):
            executor.migrate([self.migrate_to])

        GradeRevision = self.old_apps.get_model("assessment", "GradeRevision")
        Grade = self.old_apps.get_model("assessment", "Grade")
        Submission = self.old_apps.get_model("assessment", "Submission")
        GradeRevision.objects.all().delete()
        Grade.objects.all().delete()
        Submission.objects.all().delete()
