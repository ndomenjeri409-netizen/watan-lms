from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.academics.models import Course, CourseModule
from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.cms.models import ContentPage
from apps.files.models import StoredFile
from apps.files.storage import StorageNotConfigured
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import Student
from tests.helpers import create_role_user


class SprintTwoAcademicsTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        self.unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department = Department.objects.create(
            unit=self.unit, campus=campus, name="Travel", code="TRV"
        )
        self.other_department = Department.objects.create(
            unit=self.unit, campus=campus, name="Hospitality", code="HSP"
        )
        self.hod = create_role_user("hod", role=Role.HOD)
        RoleScope.objects.create(user=self.hod, department=self.department)
        self.admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.student = User.objects.create_user("student")
        Student.objects.create(
            user=self.student,
            department=self.department,
            registration_number="TRV-2026-0097",
            first_name="Student",
            last_name="User",
            email="student@example.test",
            admission_year=2026,
        )
        self.teacher = create_role_user("teacher", role=Role.TEACHER)
        self.published_course = Course.objects.create(
            department=self.department,
            created_by=self.hod,
            title="Public course",
            code="PUB-1",
            status=Course.Status.PUBLISHED,
        )
        self.draft_course = Course.objects.create(
            department=self.other_department,
            created_by=self.admin,
            title="Private course",
            code="DRF-1",
        )

    def test_public_and_student_catalog_only_exposes_published_courses(self):
        response = self.client.get("/api/v1/courses/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["code"] for item in response.json()["results"]}, {"PUB-1"}
        )

        self.client.force_authenticate(self.student)
        response = self.client.get("/api/v1/courses/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["code"] for item in response.json()["results"]}, {"PUB-1"}
        )
        self.assertEqual(
            self.client.get(f"/api/v1/courses/{self.draft_course.slug}/").status_code,
            404,
        )

    def test_hod_course_scope_and_course_create_audit(self):
        self.client.force_authenticate(self.hod)
        response = self.client.get("/api/v1/courses/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["code"] for item in response.json()["results"]}, {"PUB-1"}
        )

        response = self.client.post(
            "/api/v1/courses/",
            {
                "department": str(self.department.id),
                "title": "New course",
                "code": "NEW-1",
                "status": Course.Status.DRAFT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = Course.objects.get(code="NEW-1")
        self.assertEqual(created.created_by, self.hod)
        self.assertTrue(
            AuditLog.objects.filter(
                action="created", object_id=str(created.id)
            ).exists()
        )

        response = self.client.post(
            "/api/v1/courses/",
            {
                "department": str(self.other_department.id),
                "title": "Out-of-scope course",
                "code": "OUT-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Course.objects.filter(code="OUT-1").exists())

    def test_teacher_cannot_create_course_but_can_edit_own_course_content(self):
        self.client.force_authenticate(self.teacher)
        response = self.client.post(
            "/api/v1/courses/",
            {
                "department": str(self.department.id),
                "title": "Unauthorized course",
                "code": "NO-1",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

        course = Course.objects.create(
            department=self.department,
            created_by=self.teacher,
            title="Teacher course",
            code="TCH-1",
        )
        response = self.client.post(
            "/api/v1/course-modules/",
            {
                "course": str(course.id),
                "title": "Module 1",
                "position": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            CourseModule.objects.filter(course=course, title="Module 1").exists()
        )

        response = self.client.post(
            "/api/v1/course-modules/",
            {
                "course": str(self.published_course.id),
                "title": "Not assigned",
                "position": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_public_cms_api_hides_drafts(self):
        ContentPage.objects.create(
            title="About", slug="about", body="Public page", is_published=True
        )
        ContentPage.objects.create(
            title="Internal", slug="internal", body="Draft page", is_published=False
        )

        response = self.client.get("/api/v1/pages/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["slug"] for item in response.json()["results"]}, {"about"}
        )

        self.client.force_authenticate(self.admin)
        response = self.client.get("/api/v1/pages/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["slug"] for item in response.json()["results"]},
            {"about", "internal"},
        )

    @patch("apps.files.views.get_storage_client", side_effect=StorageNotConfigured)
    def test_file_upload_reports_unconfigured_object_storage(self, get_storage_client):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/files/uploads/",
            {
                "purpose": "cover_image",
                "filename": "cover.png",
                "content_type": "image/png",
                "size": 1024,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "SERVICE_UNAVAILABLE")

    @override_settings(FILE_STORAGE_QUOTA_BYTES=1024)
    @patch("apps.files.views.get_storage_client")
    def test_file_upload_enforces_per_user_storage_quota(self, get_storage_client):
        get_storage_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example/upload"
        )
        StoredFile.objects.create(
            purpose=StoredFile.Purpose.COVER_IMAGE,
            owner_user=self.admin,
            object_key="cover/existing",
            original_name="existing.png",
            content_type="image/png",
            size_bytes=800,
            status=StoredFile.Status.READY,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/files/uploads/",
            {
                "purpose": "cover_image",
                "filename": "new.png",
                "content_type": "image/png",
                "size": 300,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(StoredFile.objects.count(), 1)
