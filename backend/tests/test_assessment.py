from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.assessment.models import (
    Assessment,
    AssessmentAttemptGrant,
    AssessmentTemplate,
    Grade,
    GradeRevision,
    GradeSupersession,
    Submission,
    TranscriptVersion,
)
from apps.enrollment.models import CourseAccess, Enrollment
from apps.files.models import StoredFile
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import Student
from apps.scheduling.models import ClassGroup, ClassTeacher
from tests.helpers import create_role_user


def make_assessment(
    *,
    course,
    created_by,
    title,
    kind,
    maximum_score,
    instructions="",
    class_group=None,
    due_at=None,
    status=Assessment.Status.DRAFT,
    weight=1,
    max_attempts=1,
    late_until=None,
):
    template = AssessmentTemplate.objects.create(
        course=course,
        created_by=created_by,
        title=title,
        instructions=instructions,
        kind=kind,
        maximum_score=maximum_score,
    )
    return Assessment.objects.create(
        template=template,
        class_group=class_group,
        due_at=due_at,
        late_until=late_until,
        max_attempts=max_attempts,
        status=status,
        weight=weight,
    )


class AssessmentFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department = Department.objects.create(
            unit=unit, campus=campus, name="Travel", code="TRV"
        )
        self.admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.teacher = create_role_user("teacher", role=Role.TEACHER)
        self.hod = create_role_user("hod", role=Role.HOD)
        self.student_user = User.objects.create_user("student", role=Role.STUDENT)
        RoleScope.objects.create(user=self.hod, department=self.department)
        self.course = Course.objects.create(
            department=self.department,
            created_by=self.admin,
            title="Travel operations",
            code="TRV-101",
            status=Course.Status.PUBLISHED,
        )
        self.group = ClassGroup.objects.create(
            course=self.course,
            name="Group A",
            code="TRV-101-A",
        )
        ClassTeacher.objects.create(
            class_group=self.group,
            teacher=self.teacher,
            role=ClassTeacher.Role.LEAD,
        )
        self.student = Student.objects.create(
            user=self.student_user,
            department=self.department,
            registration_number="TRV-2026-0001",
            first_name="Amina",
            last_name="Njeri",
            email="amina@example.test",
            admission_year=2026,
        )
        enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            class_group=self.group,
            status=Enrollment.Status.ACTIVE,
        )
        CourseAccess.objects.create(
            student=self.student,
            course=self.course,
            enrollment=enrollment,
            is_active=True,
        )
        self.assessment = make_assessment(
            course=self.course,
            class_group=self.group,
            created_by=self.teacher,
            title="Field report",
            instructions="Submit a field report.",
            kind=Assessment.Kind.ASSIGNMENT,
            maximum_score="100.00",
            due_at=timezone.now() + timedelta(days=3),
            status=Assessment.Status.PUBLISHED,
        )

    def create_submission(self):
        file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=self.student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="field-report.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(self.assessment.id), "file": str(file.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        return response.json(), file

    def create_pending_grade(self, assessment, student, student_user):
        file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="exam.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        submission = Submission.objects.create(
            assessment=assessment, student=student, file=file
        )
        enrollment = Enrollment.objects.get(student=student, course=self.course)
        grade = Grade.objects.create(
            assessment=assessment,
            enrollment=enrollment,
            submission=submission,
            source=Grade.Source.SUBMISSION,
            score="80.00",
            graded_by=self.teacher,
            status=Grade.Status.PENDING_APPROVAL,
        )
        GradeRevision.objects.create(
            grade=grade,
            revision=grade.revision,
            submission=submission,
            source=Grade.Source.SUBMISSION,
            attempt_number=submission.attempt_number,
            score=grade.score,
            feedback=grade.feedback,
            status=grade.status,
            changed_by=self.teacher,
        )
        return grade

    def test_class_completes_only_after_all_active_exam_grades_are_approved(self):
        self.client.force_authenticate(self.admin)
        for target in (ClassGroup.Status.OPEN, ClassGroup.Status.RUNNING):
            response = self.client.post(
                f"/api/v1/class-groups/{self.group.pk}/transition/",
                {"status": target},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.content)

        exam = make_assessment(
            course=self.course,
            class_group=self.group,
            created_by=self.teacher,
            title="Final exam",
            kind=Assessment.Kind.EXAM,
            maximum_score="100.00",
            status=Assessment.Status.PUBLISHED,
        )
        second_user = User.objects.create_user("student-two", role=Role.STUDENT)
        second_student = Student.objects.create(
            user=second_user,
            department=self.department,
            registration_number="TRV-2026-0002",
            first_name="Kendi",
            last_name="Wanjiku",
            email="kendi@example.test",
            admission_year=2026,
        )
        second_enrollment = Enrollment.objects.create(
            student=second_student,
            course=self.course,
            class_group=self.group,
            status=Enrollment.Status.ACTIVE,
        )
        CourseAccess.objects.create(
            student=second_student,
            course=self.course,
            enrollment=second_enrollment,
        )
        grades = [
            self.create_pending_grade(exam, self.student, self.student_user),
            self.create_pending_grade(exam, second_student, second_user),
        ]

        self.client.force_authenticate(self.hod)
        first_approval = self.client.post(
            f"/api/v1/grades/{grades[0].pk}/approve/", {}, format="json"
        )
        self.assertEqual(first_approval.status_code, 200, first_approval.content)
        self.assertEqual(first_approval.json()["status"], Grade.Status.APPROVED)
        self.group.refresh_from_db()
        self.assertEqual(self.group.status, ClassGroup.Status.RUNNING)
        first_publication = self.client.post(
            f"/api/v1/grades/{grades[0].pk}/publish/", {}, format="json"
        )
        self.assertEqual(first_publication.status_code, 200, first_publication.content)

        self.client.force_authenticate(self.admin)
        premature_completion = self.client.post(
            f"/api/v1/class-groups/{self.group.pk}/transition/",
            {"status": ClassGroup.Status.COMPLETED},
            format="json",
        )
        self.assertEqual(premature_completion.status_code, 400)

        self.client.force_authenticate(self.hod)
        final_approval = self.client.post(
            f"/api/v1/grades/{grades[1].pk}/approve/", {}, format="json"
        )
        self.assertEqual(final_approval.status_code, 200, final_approval.content)
        final_publication = self.client.post(
            f"/api/v1/grades/{grades[1].pk}/publish/", {}, format="json"
        )
        self.assertEqual(final_publication.status_code, 200, final_publication.content)
        self.group.refresh_from_db()
        self.assertEqual(self.group.status, ClassGroup.Status.COMPLETED)

        file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=second_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="late-exam.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(second_user)
        late_submission = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(exam.pk), "file": str(file.pk)},
            format="json",
        )
        self.assertEqual(late_submission.status_code, 400, late_submission.content)

    def test_class_teacher_can_grade_only_assigned_class(self):
        assistant = create_role_user("assessment-assistant", role=Role.TEACHER)
        ClassTeacher.objects.create(
            class_group=self.group,
            teacher=assistant,
            role=ClassTeacher.Role.ASSISTANT,
        )
        own_submission, _ = self.create_submission()

        other_teacher = create_role_user("other-class-teacher", role=Role.TEACHER)
        other_group = ClassGroup.objects.create(
            course=self.course,
            name="Group B",
            code="TRV-101-B",
        )
        ClassTeacher.objects.create(
            class_group=other_group,
            teacher=other_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        other_assessment = make_assessment(
            course=self.course,
            class_group=other_group,
            created_by=other_teacher,
            title="Other class report",
            kind=Assessment.Kind.ASSIGNMENT,
            maximum_score="100.00",
            status=Assessment.Status.PUBLISHED,
        )
        other_student_user = User.objects.create_user(
            "other-class-student", role=Role.STUDENT
        )
        other_student = Student.objects.create(
            user=other_student_user,
            department=self.department,
            registration_number="TRV-2026-0003",
            first_name="Wanjiku",
            last_name="Kendi",
            email="wanjiku@example.test",
            admission_year=2026,
        )
        other_enrollment = Enrollment.objects.create(
            student=other_student,
            course=self.course,
            class_group=other_group,
            status=Enrollment.Status.ACTIVE,
        )
        CourseAccess.objects.create(
            student=other_student,
            course=self.course,
            enrollment=other_enrollment,
        )
        other_file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=other_student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="other-report.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(other_student_user)
        other_response = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(other_assessment.id), "file": str(other_file.id)},
            format="json",
        )
        self.assertEqual(other_response.status_code, 201, other_response.content)

        self.client.force_authenticate(assistant)
        assessments = self.client.get("/api/v1/assessments/")
        self.assertEqual(assessments.status_code, 200)
        self.assertEqual(
            {item["id"] for item in assessments.json()["results"]},
            {str(self.assessment.id)},
        )
        own_grade = Grade.objects.get(submission_id=own_submission["id"])
        own_grade_response = self.client.patch(
            f"/api/v1/grades/{own_grade.pk}/",
            {"score": "85.00"},
            format="json",
        )
        self.assertEqual(
            own_grade_response.status_code, 200, own_grade_response.content
        )
        other_grade = Grade.objects.get(submission_id=other_response.json()["id"])
        other_grade_response = self.client.patch(
            f"/api/v1/grades/{other_grade.pk}/",
            {"score": "85.00"},
            format="json",
        )
        self.assertEqual(
            other_grade_response.status_code, 404, other_grade_response.content
        )

    def test_submit_grade_approve_and_view_gradebook_and_transcript(self):
        submission_data, _ = self.create_submission()
        grade = Grade.objects.get(submission_id=submission_data["id"])
        self.client.force_authenticate(self.teacher)
        response = self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "87.50", "feedback": "Strong analysis."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        grade_id = response.json()["id"]
        response = self.client.post(
            f"/api/v1/grades/{grade_id}/submit-for-approval/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.PENDING_APPROVAL)

        self.client.force_authenticate(self.hod)
        response = self.client.post(
            f"/api/v1/grades/{grade_id}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.APPROVED)
        response = self.client.post(
            f"/api/v1/grades/{grade_id}/publish/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.PUBLISHED)
        self.assertEqual(response.json()["revision"], 5)
        self.assertEqual(GradeRevision.objects.filter(grade_id=grade_id).count(), 5)
        response = self.client.get(f"/api/v1/grades/{grade_id}/revisions/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 5)

        self.client.force_authenticate(self.student_user)
        response = self.client.get(f"/api/v1/grades/{grade_id}/revisions/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["count"], 1)
        response = self.client.get("/api/v1/grades/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"][0]["score"], "87.50")
        response = self.client.get(f"/api/v1/gradebook/?course={self.course.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["students"][0]["grades"][str(self.assessment.id)]["score"],
            "87.50",
        )
        response = self.client.get(f"/api/v1/transcripts/{self.student.id}/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        response = self.client.get("/api/v1/transcripts/me/")
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.content.startswith(b"%PDF"))
        first_version = TranscriptVersion.objects.get(student=self.student, version=1)
        self.assertEqual(first_version.snapshot[0]["score"], "87.50")

        grade = Grade.objects.get(pk=grade_id)
        self.client.force_authenticate(self.teacher)
        response = self.client.patch(
            f"/api/v1/grades/{grade_id}/",
            {"score": "91.00", "feedback": "Rechecked."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_authenticate(self.student_user)
        response = self.client.get("/api/v1/grades/")
        current_grade = response.json()["results"][0]
        self.assertEqual(current_grade["score"], "87.50")
        self.assertTrue(current_grade["regrade_pending"])

        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            f"/api/v1/grades/{grade_id}/submit-for-approval/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.client.force_authenticate(self.hod)
        response = self.client.post(
            f"/api/v1/grades/{grade_id}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.APPROVED)
        self.assertEqual(
            TranscriptVersion.objects.filter(student=self.student).count(), 1
        )
        response = self.client.post(
            f"/api/v1/grades/{grade_id}/publish/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(GradeSupersession.objects.count(), 1)
        versions = list(
            TranscriptVersion.objects.filter(student=self.student).order_by("version")
        )
        self.assertEqual(len(versions), 2)
        self.assertEqual(versions[1].snapshot[0]["score"], "91.00")
        self.assertTrue(versions[1].is_revised)
        self.assertIsNotNone(versions[1].revision_date)
        self.assertEqual(
            Grade.objects.get(pk=grade_id).official_revision_id,
            GradeRevision.objects.filter(
                grade_id=grade_id, status=Grade.Status.PUBLISHED
            )
            .order_by("-revision")
            .first()
            .id,
        )

    def test_attempt_grant_adds_one_enrollment_scoped_submission(self):
        _first_submission, _ = self.create_submission()
        enrollment = Enrollment.objects.get(student=self.student, course=self.course)
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            f"/api/v1/assessments/{self.assessment.id}/re-open/",
            {"enrollment": str(enrollment.id), "reason": "Approved resit."},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        grant_id = response.json()["id"]
        grant = AssessmentAttemptGrant.objects.get(pk=grant_id)
        self.assertEqual(grant.enrollment_id, enrollment.id)
        self.assertGreater(grant.valid_until, timezone.now() + timedelta(days=6))

        file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=self.student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="resit.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(self.assessment.id), "file": str(file.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["attempt_number"], 2)
        grant.refresh_from_db()
        self.assertIsNotNone(grant.used_at)
        self.assertEqual(grant.used_for, Grade.Source.SUBMISSION)
        self.assertEqual(
            GradeRevision.objects.filter(
                grade__submission_id=response.json()["id"],
                attempt_grant=grant,
            ).count(),
            1,
        )

        third_file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=self.student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="third.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        response = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(self.assessment.id), "file": str(third_file.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_offline_mark_has_no_submission_or_attempt_count(self):
        enrollment = Enrollment.objects.get(student=self.student, course=self.course)
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/grades/",
            {
                "assessment": str(self.assessment.id),
                "enrollment": str(enrollment.id),
                "score": "76.00",
                "feedback": "Recorded from signed paper.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(
            "/api/v1/grades/",
            {
                "assessment": str(self.assessment.id),
                "enrollment": str(enrollment.id),
                "score": "76.00",
                "feedback": "Recorded from signed paper.",
                "change_note": "Transcribed from the signed paper mark sheet.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        grade = Grade.objects.get(pk=response.json()["id"])
        self.assertEqual(grade.source, Grade.Source.STAFF_RECORDED)
        self.assertIsNone(grade.submission_id)
        self.assertEqual(Submission.objects.count(), 0)
        self.assertEqual(GradeRevision.objects.count(), 1)
        self.assertEqual(GradeRevision.objects.first().attempt_number, None)
        self.assertEqual(
            GradeRevision.objects.first().change_note,
            "Transcribed from the signed paper mark sheet.",
        )

    def test_resubmission_increments_attempt_and_invalid_grade_is_rejected(self):
        self.assessment.max_attempts = 2
        self.assessment.save(update_fields=("max_attempts", "updated_at"))
        first_submission, _ = self.create_submission()
        second_submission, _ = self.create_submission()
        self.assertEqual(first_submission["attempt_number"], 1)
        self.assertEqual(second_submission["attempt_number"], 2)

        self.client.force_authenticate(self.teacher)
        grade = Grade.objects.get(submission_id=second_submission["id"])
        response = self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "101.00", "feedback": ""},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(Grade.objects.count(), 1)
        third_submission_file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=self.student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="third-report.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/submissions/",
            {
                "assessment": str(self.assessment.id),
                "file": str(third_submission_file.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_teacher_cannot_download_student_submission(self):
        _, file = self.create_submission()
        self.client.force_authenticate(self.student_user)
        response = self.client.get(f"/api/v1/files/{file.id}/download-url/")
        self.assertEqual(response.status_code, 403)

        other_teacher = create_role_user("other-teacher", role=Role.TEACHER)
        self.client.force_authenticate(other_teacher)
        response = self.client.get(f"/api/v1/files/{file.id}/download-url/")
        self.assertEqual(response.status_code, 403)

        self.client.force_authenticate(self.teacher)
        with patch("apps.files.views.get_storage_client") as storage_client:
            storage_client.return_value.generate_presigned_url.return_value = (
                "https://storage.example.test/signed"
            )
            response = self.client.get(f"/api/v1/files/{file.id}/download-url/")
        self.assertEqual(response.status_code, 200, response.content)

    def test_student_cannot_submit_after_deadline_or_without_course_access(self):
        self.assessment.due_at = timezone.now() - timedelta(seconds=1)
        self.assessment.save(update_fields=("due_at", "updated_at"))
        file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=self.student_user,
            object_key=f"submission/{uuid4().hex}",
            original_name="late.pdf",
            content_type="application/pdf",
            size_bytes=50,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(self.assessment.id), "file": str(file.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(Submission.objects.exists())

        self.assessment.due_at = timezone.now() + timedelta(days=1)
        self.assessment.save(update_fields=("due_at", "updated_at"))
        CourseAccess.objects.filter(student=self.student).update(is_active=False)
        response = self.client.post(
            "/api/v1/submissions/",
            {"assessment": str(self.assessment.id), "file": str(file.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
        self.assertFalse(Submission.objects.exists())

    def test_hod_cannot_approve_grades_outside_their_scope(self):
        outsider_hod = create_role_user("outsider-hod", role=Role.HOD)
        submission, _ = self.create_submission()
        grade = Grade.objects.get(submission_id=submission["id"])
        self.client.force_authenticate(self.teacher)
        self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "80.00", "feedback": ""},
            format="json",
        )
        self.client.post(
            f"/api/v1/grades/{grade.pk}/submit-for-approval/", {}, format="json"
        )
        self.client.force_authenticate(outsider_hod)
        response = self.client.post(
            f"/api/v1/grades/{grade.pk}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_returned_grade_is_revisioned_and_can_be_resubmitted(self):
        submission, _ = self.create_submission()
        grade = Grade.objects.get(submission_id=submission["id"])
        self.client.force_authenticate(self.teacher)
        self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "72.00", "feedback": "Needs revision."},
            format="json",
        )
        self.client.post(
            f"/api/v1/grades/{grade.pk}/submit-for-approval/", {}, format="json"
        )
        self.client.force_authenticate(self.hod)
        response = self.client.post(
            f"/api/v1/grades/{grade.pk}/reject/",
            {"note": "Please review the calculation."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.REJECTED)
        response = self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "90.00", "feedback": "Not authorized."},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)

        self.client.force_authenticate(self.teacher)
        response = self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "82.00", "feedback": "Calculation corrected."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.DRAFT)
        self.assertEqual(response.json()["revision"], 5)
        self.assertEqual(GradeRevision.objects.filter(grade_id=grade.pk).count(), 5)
        response = self.client.delete(f"/api/v1/grades/{grade.pk}/")
        self.assertEqual(response.status_code, 405)

    def test_teacher_and_unit_manager_assessment_scopes_union_by_assignment(self):
        user = User.objects.create_user("assessment-teacher-manager")
        RoleAssignment.objects.create(
            user=user, role=Role.TEACHER, unit=self.course.unit
        )
        wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.ACADEMIC
        )
        wta_department = Department.objects.create(
            unit=wta,
            campus=self.department.campus,
            name="Agency",
            code="AGY",
        )
        RoleAssignment.objects.create(user=user, role=Role.UNIT_MANAGER, unit=wta)
        ClassTeacher.objects.create(
            class_group=self.group,
            teacher=user,
            role=ClassTeacher.Role.ASSISTANT,
        )

        other_teacher = create_role_user("assessment-other-teacher", role=Role.TEACHER)
        other_group = ClassGroup.objects.create(
            course=self.course,
            name="Other group",
            code="TRV-101-OTHER",
        )
        ClassTeacher.objects.create(
            class_group=other_group,
            teacher=other_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        other_assessment = make_assessment(
            course=self.course,
            class_group=other_group,
            created_by=other_teacher,
            title="Other teacher assessment",
            kind=Assessment.Kind.ASSIGNMENT,
            maximum_score="100.00",
        )
        manager_course = Course.objects.create(
            department=wta_department,
            created_by=self.admin,
            title="Agency course",
            code="AGY-101",
            status=Course.Status.PUBLISHED,
        )
        manager_group = ClassGroup.objects.create(
            course=manager_course,
            name="Agency group",
            code="AGY-101-A",
        )
        manager_assessment = make_assessment(
            course=manager_course,
            class_group=manager_group,
            created_by=self.admin,
            title="Agency assessment",
            kind=Assessment.Kind.ASSIGNMENT,
            maximum_score="100.00",
            status=Assessment.Status.PUBLISHED,
        )

        manager_user = User.objects.create_user(
            "assessment-manager-student", role=Role.STUDENT
        )
        manager_student = Student.objects.create(
            user=manager_user,
            department=wta_department,
            registration_number="AGY-2026-0001",
            first_name="Nia",
            last_name="Wambui",
            email="nia@example.test",
            admission_year=2026,
        )
        manager_enrollment = Enrollment.objects.create(
            student=manager_student,
            course=manager_course,
            class_group=manager_group,
            status=Enrollment.Status.ACTIVE,
        )
        other_user = User.objects.create_user(
            "assessment-other-student", role=Role.STUDENT
        )
        other_student = Student.objects.create(
            user=other_user,
            department=self.department,
            registration_number="TRV-2026-0004",
            first_name="Asha",
            last_name="Njeri",
            email="asha@example.test",
            admission_year=2026,
        )
        other_enrollment = Enrollment.objects.create(
            student=other_student,
            course=self.course,
            class_group=other_group,
            status=Enrollment.Status.ACTIVE,
        )

        submissions = {}
        submission_specs = (
            (
                "teacher",
                self.assessment,
                self.student,
                self.student_user,
                Enrollment.objects.get(student=self.student, course=self.course),
            ),
            (
                "manager",
                manager_assessment,
                manager_student,
                manager_user,
                manager_enrollment,
            ),
            ("other", other_assessment, other_student, other_user, other_enrollment),
        )
        for key, assessment, student, owner, enrollment in submission_specs:
            file = StoredFile.objects.create(
                purpose=StoredFile.Purpose.SUBMISSION,
                owner_user=owner,
                object_key=f"submission/{uuid4().hex}",
                original_name=f"{key}.pdf",
                content_type="application/pdf",
                size_bytes=1234,
                status=StoredFile.Status.READY,
            )
            submissions[key] = Submission.objects.create(
                assessment=assessment,
                student=student,
                file=file,
            )
            Grade.objects.create(
                assessment=assessment,
                enrollment=enrollment,
                submission=submissions[key],
                source=Grade.Source.SUBMISSION,
                score="80.00",
                graded_by=self.admin,
            )

        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/assessments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["results"]},
            {str(self.assessment.id), str(manager_assessment.id)},
        )
        self.assertEqual(
            set(Submission.objects.for_user(user).values_list("id", flat=True)),
            {submissions["teacher"].id, submissions["manager"].id},
        )
        self.assertEqual(
            set(Grade.objects.for_user(user).values_list("id", flat=True)),
            {
                Grade.objects.get(submission=submissions["teacher"]).id,
                Grade.objects.get(submission=submissions["manager"]).id,
            },
        )

        template_response = self.client.post(
            "/api/v1/assessment-templates/",
            {
                "course": str(manager_course.id),
                "title": "Manager-created assessment",
                "kind": Assessment.Kind.QUIZ,
                "maximum_score": "20.00",
            },
            format="json",
        )
        self.assertEqual(template_response.status_code, 201, template_response.content)
        response = self.client.post(
            "/api/v1/assessments/",
            {
                "template": template_response.json()["id"],
                "class_group": str(manager_group.id),
                "weight": "1.50",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["weight"], "1.50")

        response = self.client.get(f"/api/v1/gradebook/?course={manager_course.id}")
        self.assertEqual(response.status_code, 200, response.content)

    def test_director_and_auditor_can_read_but_not_write_assessments(self):
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = create_role_user(f"assessment-{role.lower()}", role=role)
            self.client.force_authenticate(user)

            response = self.client.get("/api/v1/assessments/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                str(self.assessment.id),
                {item["id"] for item in response.json()["results"]},
            )

            response = self.client.post(
                "/api/v1/assessment-templates/",
                {
                    "course": str(self.course.id),
                    "title": "Unauthorized assessment",
                    "kind": Assessment.Kind.QUIZ,
                    "maximum_score": "20.00",
                },
                format="json",
            )
            self.assertEqual(response.status_code, 403)

            response = self.client.get(f"/api/v1/transcripts/{self.student.id}/")
            self.assertEqual(response.status_code, 200)

    def test_hod_role_does_not_grant_teacher_only_grade_actions(self):
        user = User.objects.create_user("assessment-hod-teacher")
        RoleAssignment.objects.create(user=user, role=Role.HOD, unit=self.course.unit)
        RoleAssignment.objects.create(
            user=user, role=Role.TEACHER, unit=self.course.unit
        )
        RoleScope.objects.create(user=user, department=self.department)
        submission, _ = self.create_submission()
        grade = Grade.objects.get(submission_id=submission["id"])

        self.client.force_authenticate(user)
        response = self.client.patch(
            f"/api/v1/grades/{grade.pk}/",
            {"score": "85.00"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
