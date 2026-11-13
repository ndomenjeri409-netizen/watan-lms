from unittest.mock import patch
from uuid import uuid4

from django.test import TestCase
from rest_framework.test import APIClient

from apps.academics.models import (
    Course,
    CourseAssignment,
    CourseModule,
    Lesson,
    Material,
    Unit,
)
from apps.accounts.models import RoleAssignment, User
from apps.accounts.roles import Role
from apps.files.models import StoredFile
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import Student
from tests.helpers import create_role_user


class FileAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        self.wti = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.wti_department = Department.objects.create(
            unit=self.wti, campus=campus, name="Travel", code="TRV"
        )
        self.wta_department = Department.objects.create(
            unit=self.wta, campus=campus, name="Agency", code="AGY"
        )
        self.user = User.objects.create_user("teacher-manager")
        RoleAssignment.objects.create(user=self.user, role=Role.TEACHER, unit=self.wti)
        RoleAssignment.objects.create(
            user=self.user, role=Role.UNIT_MANAGER, unit=self.wta
        )
        self.teacher_course = Course.objects.create(
            department=self.wti_department,
            created_by=self.user,
            title="Teacher course",
            code="TRV-101",
        )
        self.manager_course = Course.objects.create(
            department=self.wta_department,
            created_by=self.user,
            title="Manager course",
            code="AGY-101",
        )
        self.other_course = Course.objects.create(
            department=self.wti_department,
            created_by=self.user,
            title="Unassigned course",
            code="TRV-102",
        )
        CourseAssignment.objects.create(
            course=self.teacher_course,
            teacher=self.user,
            can_edit_content=True,
        )
        self.teacher_file = self.create_cover_file("teacher")
        self.manager_file = self.create_cover_file("manager")
        self.other_file = self.create_cover_file("other")
        self.teacher_course.cover_image = self.teacher_file
        self.teacher_course.save(update_fields=("cover_image", "updated_at"))
        self.manager_course.cover_image = self.manager_file
        self.manager_course.save(update_fields=("cover_image", "updated_at"))
        self.other_course.cover_image = self.other_file
        self.other_course.save(update_fields=("cover_image", "updated_at"))

    def create_cover_file(self, prefix):
        return StoredFile.objects.create(
            purpose=StoredFile.Purpose.COVER_IMAGE,
            owner_user=self.user,
            object_key=f"cover/{prefix}/{uuid4().hex}",
            original_name=f"{prefix}.png",
            content_type="image/png",
            size_bytes=1024,
            status=StoredFile.Status.READY,
        )

    def create_material_file(self, prefix):
        return StoredFile.objects.create(
            purpose=StoredFile.Purpose.MATERIAL,
            owner_user=self.user,
            object_key=f"material/{prefix}/{uuid4().hex}",
            original_name=f"{prefix}.pdf",
            content_type="application/pdf",
            size_bytes=1024,
            status=StoredFile.Status.READY,
        )

    @patch("apps.files.views.get_storage_client")
    def test_download_access_unions_teacher_assignment_and_manager_unit(
        self, get_client
    ):
        get_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example.test/signed"
        )
        self.client.force_authenticate(self.user)

        for stored_file in (self.teacher_file, self.manager_file):
            response = self.client.get(f"/api/v1/files/{stored_file.id}/download-url/")
            self.assertEqual(response.status_code, 200, response.content)

        response = self.client.get(f"/api/v1/files/{self.other_file.id}/download-url/")
        self.assertEqual(response.status_code, 403)

    @patch("apps.files.views.get_storage_client")
    def test_hidden_course_material_cannot_be_downloaded_by_students(self, get_client):
        get_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example.test/signed"
        )
        self.teacher_course.status = Course.Status.PUBLISHED
        self.teacher_course.save(update_fields=("status", "updated_at"))
        module = CourseModule.objects.create(
            course=self.teacher_course,
            title="Module",
            position=1,
        )
        unit = Unit.objects.create(module=module, title="Topic", position=1)
        lesson = Lesson.objects.create(unit=unit, title="Lesson", position=1)
        visible_file = self.create_material_file("visible")
        hidden_file = self.create_material_file("hidden")
        Material.objects.create(
            lesson=lesson,
            title="Visible file",
            kind=Material.Kind.FILE,
            file=visible_file,
        )
        Material.objects.create(
            lesson=lesson,
            title="Hidden file",
            kind=Material.Kind.FILE,
            file=hidden_file,
            is_visible=False,
        )
        student = User.objects.create_user("material-student")

        self.client.force_authenticate(None)
        response = self.client.get(f"/api/v1/files/{visible_file.id}/download-url/")
        self.assertEqual(response.status_code, 200, response.content)
        response = self.client.get(f"/api/v1/files/{hidden_file.id}/download-url/")
        self.assertEqual(response.status_code, 403, response.content)

        self.client.force_authenticate(student)
        response = self.client.get(f"/api/v1/files/{hidden_file.id}/download-url/")
        self.assertEqual(response.status_code, 403, response.content)

        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/v1/files/{hidden_file.id}/download-url/")
        self.assertEqual(response.status_code, 200, response.content)

    @patch("apps.files.views.get_storage_client")
    def test_unit_manager_can_upload_course_material(self, get_client):
        manager = User.objects.create_user("wta-manager")
        RoleAssignment.objects.create(
            user=manager, role=Role.UNIT_MANAGER, unit=self.wta
        )
        get_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example.test/upload"
        )
        self.client.force_authenticate(manager)

        response = self.client.post(
            "/api/v1/files/uploads/",
            {
                "purpose": StoredFile.Purpose.MATERIAL,
                "filename": "lesson.pdf",
                "content_type": "application/pdf",
                "size": 1024,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    @patch("apps.files.views.get_storage_client")
    def test_profile_photo_upload_role_matrix(self, get_client):
        get_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example.test/upload"
        )
        allowed = (
            create_role_user("photo-admin", role=Role.ADMIN),
            create_role_user("photo-super-admin", role=Role.SUPER_ADMIN),
            create_role_user("photo-manager", role=Role.UNIT_MANAGER, unit=self.wti),
            create_role_user("photo-bursar", role=Role.BURSAR, unit=self.wti),
        )
        denied = (
            create_role_user("photo-director", role=Role.DIRECTOR),
            create_role_user("photo-auditor", role=Role.AUDITOR),
            create_role_user("photo-teacher", role=Role.TEACHER, unit=self.wti),
            create_role_user("photo-cashier", role=Role.CASHIER, unit=self.wti),
            User.objects.create_user("photo-student"),
        )
        payload = {
            "purpose": StoredFile.Purpose.PROFILE_PHOTO,
            "filename": "student.png",
            "content_type": "image/png",
            "size": 1024,
        }
        for actor in allowed:
            with self.subTest(actor=actor.firebase_uid):
                self.client.force_authenticate(actor)
                response = self.client.post(
                    "/api/v1/files/uploads/", payload, format="json"
                )
                self.assertEqual(response.status_code, 201, response.content)
        for actor in denied:
            with self.subTest(actor=actor.firebase_uid):
                self.client.force_authenticate(actor)
                response = self.client.post(
                    "/api/v1/files/uploads/", payload, format="json"
                )
                expected_status = (
                    403 if actor.has_role_global(Role.DIRECTOR, Role.AUDITOR) else 400
                )
                self.assertEqual(
                    response.status_code, expected_status, response.content
                )
        self.assertEqual(
            StoredFile.objects.filter(purpose=StoredFile.Purpose.PROFILE_PHOTO).count(),
            len(allowed),
        )

    @patch("apps.files.views.get_storage_client")
    def test_profile_photo_download_uses_scoped_restricted_access(self, get_client):
        get_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example.test/signed"
        )
        wti_student = Student.objects.create(
            department=self.wti_department,
            registration_number="WTI/TRV/2026/0001",
            first_name="WTI",
            last_name="Student",
            email="wti-student@example.test",
            admission_year=2026,
        )
        wta_student = Student.objects.create(
            department=self.wta_department,
            registration_number="WTA/AGY/2026/0001",
            first_name="WTA",
            last_name="Student",
            email="wta-student@example.test",
            admission_year=2026,
        )
        wti_photo = StoredFile.objects.create(
            purpose=StoredFile.Purpose.PROFILE_PHOTO,
            owner_user=self.user,
            object_key=f"profile-photo/wti/{uuid4().hex}",
            original_name="wti.png",
            content_type="image/png",
            size_bytes=1024,
            status=StoredFile.Status.READY,
        )
        wta_photo = StoredFile.objects.create(
            purpose=StoredFile.Purpose.PROFILE_PHOTO,
            owner_user=self.user,
            object_key=f"profile-photo/wta/{uuid4().hex}",
            original_name="wta.png",
            content_type="image/png",
            size_bytes=1024,
            status=StoredFile.Status.READY,
        )
        wti_student.photo_file = wti_photo
        wti_student.save(update_fields=("photo_file", "updated_at"))
        wta_student.photo_file = wta_photo
        wta_student.save(update_fields=("photo_file", "updated_at"))

        self.client.force_authenticate(self.user)
        response = self.client.get(f"/api/v1/files/{wti_photo.pk}/download-url/")
        self.assertEqual(response.status_code, 403)
        response = self.client.get(f"/api/v1/files/{wta_photo.pk}/download-url/")
        self.assertEqual(response.status_code, 200, response.content)

        admin = create_role_user("photo-download-admin", role=Role.ADMIN)
        self.client.force_authenticate(admin)
        response = self.client.get(f"/api/v1/files/{wti_photo.pk}/download-url/")
        self.assertEqual(response.status_code, 200, response.content)

        unlinked_photo = StoredFile.objects.create(
            purpose=StoredFile.Purpose.PROFILE_PHOTO,
            owner_user=self.user,
            object_key=f"profile-photo/unlinked/{uuid4().hex}",
            original_name="unlinked.png",
            content_type="image/png",
            size_bytes=1024,
            status=StoredFile.Status.READY,
        )
        response = self.client.get(f"/api/v1/files/{unlinked_photo.pk}/download-url/")
        self.assertEqual(response.status_code, 403)

    @patch("apps.files.views.get_storage_client")
    def test_director_and_auditor_can_read_linked_files_but_cannot_upload(
        self, get_client
    ):
        get_client.return_value.generate_presigned_url.return_value = (
            "https://storage.example.test/signed"
        )
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = create_role_user(f"files-{role.lower()}", role=role)
            self.client.force_authenticate(user)

            response = self.client.get(
                f"/api/v1/files/{self.other_file.id}/download-url/"
            )
            self.assertEqual(response.status_code, 200, response.content)

            response = self.client.post(
                "/api/v1/files/uploads/",
                {
                    "purpose": StoredFile.Purpose.MATERIAL,
                    "filename": "lesson.pdf",
                    "content_type": "application/pdf",
                    "size": 1024,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 403)
