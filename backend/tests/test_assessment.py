from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.assessment.models import Assessment, Grade, GradeRevision, Submission
from apps.enrollment.models import CourseAccess, Enrollment
from apps.files.models import StoredFile
from apps.org.models import Campus, Department
from apps.people.models import Student
from apps.scheduling.models import ClassGroup
from tests.helpers import create_role_user


class AssessmentFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        self.department = Department.objects.create(
            campus=campus, name="Travel", code="TRV"
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
            teacher=self.teacher,
            name="Group A",
            code="TRV-101-A",
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
            status=Enrollment.Status.ACTIVE,
        )
        CourseAccess.objects.create(
            student=self.student,
            course=self.course,
            enrollment=enrollment,
            is_active=True,
        )
        self.assessment = Assessment.objects.create(
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

    def test_submit_grade_approve_and_view_gradebook_and_transcript(self):
        submission_data, _ = self.create_submission()
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/grades/",
            {
                "submission": submission_data["id"],
                "score": "87.50",
                "feedback": "Strong analysis.",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
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
        self.assertEqual(response.json()["status"], Grade.Status.PUBLISHED)
        self.assertEqual(response.json()["revision"], 3)
        self.assertEqual(GradeRevision.objects.filter(grade_id=grade_id).count(), 3)

        self.client.force_authenticate(self.student_user)
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

    def test_resubmission_increments_attempt_and_invalid_grade_is_rejected(self):
        first_submission, _ = self.create_submission()
        second_submission, _ = self.create_submission()
        self.assertEqual(first_submission["attempt_number"], 1)
        self.assertEqual(second_submission["attempt_number"], 2)

        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/grades/",
            {
                "submission": second_submission["id"],
                "score": "101.00",
                "feedback": "",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(Grade.objects.exists())

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
        self.client.force_authenticate(self.teacher)
        grade = self.client.post(
            "/api/v1/grades/",
            {
                "submission": submission["id"],
                "score": "80.00",
                "feedback": "",
            },
            format="json",
        ).json()
        self.client.post(
            f"/api/v1/grades/{grade['id']}/submit-for-approval/", {}, format="json"
        )
        self.client.force_authenticate(outsider_hod)
        response = self.client.post(
            f"/api/v1/grades/{grade['id']}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 404)

    def test_returned_grade_is_revisioned_and_can_be_resubmitted(self):
        submission, _ = self.create_submission()
        self.client.force_authenticate(self.teacher)
        grade = self.client.post(
            "/api/v1/grades/",
            {
                "submission": submission["id"],
                "score": "72.00",
                "feedback": "Needs revision.",
            },
            format="json",
        ).json()
        self.client.post(
            f"/api/v1/grades/{grade['id']}/submit-for-approval/", {}, format="json"
        )
        self.client.force_authenticate(self.hod)
        response = self.client.post(
            f"/api/v1/grades/{grade['id']}/reject/",
            {"note": "Please review the calculation."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.REJECTED)
        response = self.client.patch(
            f"/api/v1/grades/{grade['id']}/",
            {"score": "90.00", "feedback": "Not authorized."},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)

        self.client.force_authenticate(self.teacher)
        response = self.client.patch(
            f"/api/v1/grades/{grade['id']}/",
            {"score": "82.00", "feedback": "Calculation corrected."},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], Grade.Status.DRAFT)
        self.assertEqual(response.json()["revision"], 4)
        self.assertEqual(GradeRevision.objects.filter(grade_id=grade["id"]).count(), 4)
        response = self.client.delete(f"/api/v1/grades/{grade['id']}/")
        self.assertEqual(response.status_code, 405)
