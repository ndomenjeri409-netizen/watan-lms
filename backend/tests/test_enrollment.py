from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.enrollment.models import Application, CourseAccess, Enrollment
from apps.org.models import Campus, Department
from apps.people.models import Student, allocate_registration_number
from tests.helpers import create_role_user


class EnrollmentFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        self.department = Department.objects.create(
            campus=campus, name="Travel", code="TRV"
        )
        self.other_department = Department.objects.create(
            campus=campus, name="Hospitality", code="HSP"
        )
        self.admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.hod = create_role_user("hod", role=Role.HOD)
        RoleScope.objects.create(user=self.hod, department=self.department)
        self.course = Course.objects.create(
            department=self.department,
            created_by=self.admin,
            title="Travel operations",
            code="TRV-101",
            status=Course.Status.PUBLISHED,
        )
        self.application_data = {
            "course": str(self.course.id),
            "first_name": "Amina",
            "last_name": "Njeri",
            "email": "amina@example.test",
            "phone": "+254700000000",
            "statement": "I want to study travel operations.",
        }

    def test_public_apply_then_staff_approval_provisions_student_access(self):
        response = self.client.post(
            "/api/v1/applications/", self.application_data, format="json"
        )
        self.assertEqual(response.status_code, 201)
        application = Application.objects.get(pk=response.json()["id"])
        self.assertEqual(application.department, self.department)
        self.assertEqual(application.status, Application.Status.PENDING)
        self.assertTrue(
            AuditLog.objects.filter(
                action="application_submitted", object_id=str(application.id)
            ).exists()
        )

        self.client.force_authenticate(self.admin)
        with (
            patch("apps.enrollment.services.authentication._ensure_firebase"),
            patch(
                "apps.enrollment.services.authentication.fb_auth.create_user",
                return_value=SimpleNamespace(uid="new-student"),
            ),
            patch("apps.enrollment.services.authentication.fb_auth.delete_user"),
        ):
            response = self.client.post(
                f"/api/v1/applications/{application.id}/approve/", {}, format="json"
            )
        self.assertEqual(response.status_code, 200)

        student = Student.objects.get(email="amina@example.test")
        enrollment = Enrollment.objects.get(student=student, course=self.course)
        access = CourseAccess.objects.get(student=student, course=self.course)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.APPROVED)
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertTrue(access.is_active)
        self.assertEqual(
            student.registration_number,
            f"TRV-{timezone.localdate().year}-0001",
        )
        self.assertEqual(student.user.role, Role.STUDENT)
        self.assertTrue(
            AuditLog.objects.filter(
                action="course_access_granted", object_id=str(access.id)
            ).exists()
        )
        self.client.force_authenticate(student.user)
        response = self.client.get("/api/v1/students/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [str(student.id)]
        )

        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f"/api/v1/enrollments/{enrollment.id}/transition/",
            {"status": Enrollment.Status.COMPLETED},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        access.refresh_from_db()
        self.assertFalse(access.is_active)
        response = self.client.post(
            f"/api/v1/enrollments/{enrollment.id}/transition/",
            {"status": Enrollment.Status.ACTIVE},
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_only_hods_of_department_can_review_its_application(self):
        response = self.client.post(
            "/api/v1/applications/", self.application_data, format="json"
        )
        application_id = response.json()["id"]
        outsider = create_role_user("outsider", role=Role.HOD)
        self.client.force_authenticate(outsider)
        response = self.client.post(
            f"/api/v1/applications/{application_id}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 404)

        self.client.force_authenticate(self.hod)
        response = self.client.post(
            f"/api/v1/applications/{application_id}/reject/",
            {"note": "Please provide more information."},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], Application.Status.REJECTED)

    def test_application_requires_a_published_course_and_course_department_is_derived(
        self,
    ):
        draft = Course.objects.create(
            department=self.other_department,
            created_by=self.admin,
            title="Draft course",
            code="HSP-101",
        )
        response = self.client.post(
            "/api/v1/applications/",
            {**self.application_data, "course": str(draft.id)},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(Application.objects.exists())

    def test_registration_sequence_increments_per_department_and_year(self):
        self.assertEqual(
            allocate_registration_number(self.department, 2026), "TRV-2026-0001"
        )
        self.assertEqual(
            allocate_registration_number(self.department, 2026), "TRV-2026-0002"
        )
        self.assertEqual(
            allocate_registration_number(self.department, 2027), "TRV-2027-0001"
        )
        self.assertEqual(
            allocate_registration_number(self.other_department, 2026), "HSP-2026-0001"
        )
