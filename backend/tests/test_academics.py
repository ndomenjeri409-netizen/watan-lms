from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch
from uuid import uuid4

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings
from rest_framework.test import APIClient

from apps.academics.models import Course, CourseAssignment, CourseModule, Lesson, Unit
from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.assessment.models import Assessment, AssessmentTemplate, Grade, Submission
from apps.audit.models import AuditLog
from apps.cms.models import ContentPage
from apps.enrollment.models import CourseAccess, Enrollment
from apps.files.models import StoredFile
from apps.files.storage import StorageNotConfigured
from apps.org.models import BusinessUnit, Campus, Department, Program
from apps.people.models import Student
from apps.scheduling.models import ClassGroup
from tests.helpers import create_role_user, postgres_only


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

    def create_course_for_department_move(self, code, program=None):
        return Course.objects.create(
            department=self.department,
            program=program,
            created_by=self.admin,
            title=f"Move course {code}",
            code=code,
        )

    def move_course_to_department(self, course, actor, department):
        self.client.force_authenticate(actor)
        return self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"department": str(department.id), "version": course.version},
            format="json",
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
        CourseAssignment.objects.create(
            course=course,
            teacher=self.teacher,
            can_edit_content=True,
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

    def test_curriculum_reorder_persists_positions_and_audits_changes(self):
        self.client.force_authenticate(self.admin)
        first_module = CourseModule.objects.create(
            course=self.draft_course, title="First module", position=1
        )
        second_module = CourseModule.objects.create(
            course=self.draft_course, title="Second module", position=2
        )
        response = self.client.post(
            "/api/v1/course-modules/reorder/",
            {
                "parent_id": str(self.draft_course.id),
                "ids": [str(second_module.id), str(first_module.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        first_module.refresh_from_db()
        second_module.refresh_from_db()
        self.assertEqual((second_module.position, first_module.position), (1, 2))
        self.assertEqual(
            AuditLog.objects.filter(action="reordered").count(),
            2,
        )

        first_unit = Unit.objects.create(
            module=first_module, title="First topic", position=1
        )
        second_unit = Unit.objects.create(
            module=first_module, title="Second topic", position=2
        )
        response = self.client.post(
            "/api/v1/course-units/reorder/",
            {
                "parent_id": str(first_module.id),
                "ids": [str(second_unit.id), str(first_unit.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        first_unit.refresh_from_db()
        second_unit.refresh_from_db()
        self.assertEqual((second_unit.position, first_unit.position), (1, 2))

        first_lesson = Lesson.objects.create(
            unit=first_unit, title="First lesson", position=1
        )
        second_lesson = Lesson.objects.create(
            unit=first_unit, title="Second lesson", position=2
        )
        response = self.client.post(
            "/api/v1/lessons/reorder/",
            {
                "parent_id": str(first_unit.id),
                "ids": [str(second_lesson.id), str(first_lesson.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        first_lesson.refresh_from_db()
        second_lesson.refresh_from_db()
        self.assertEqual((second_lesson.position, first_lesson.position), (1, 2))

    @override_settings(
        COURSE_VIDEO_ALLOWED_HOSTS=("youtube.com", "youtu.be", "vimeo.com")
    )
    def test_lesson_video_url_requires_https_and_an_approved_host(self):
        self.client.force_authenticate(self.admin)
        module = CourseModule.objects.create(
            course=self.draft_course, title="Module", position=1
        )
        unit = Unit.objects.create(module=module, title="Topic", position=1)

        for url in (
            "https://www.youtube.com/watch?v=lesson",
            "https://youtu.be/lesson",
            "https://player.vimeo.com/video/1",
        ):
            response = self.client.post(
                "/api/v1/lessons/",
                {
                    "unit": str(unit.id),
                    "title": f"Lesson {url}",
                    "video_url": url,
                    "position": Lesson.objects.filter(unit=unit).count() + 1,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 201, response.content)

        for url in (
            "http://youtube.com/watch?v=lesson",
            "https://youtube.com.attacker.test/watch?v=lesson",
            "https://attacker.test/?next=youtube.com",
            "https://user@youtube.com/watch?v=lesson",
            "https://youtube.com:444/watch?v=lesson",
        ):
            response = self.client.post(
                "/api/v1/lessons/",
                {
                    "unit": str(unit.id),
                    "title": "Rejected video",
                    "video_url": url,
                    "position": Lesson.objects.filter(unit=unit).count() + 1,
                },
                format="json",
            )
            self.assertEqual(response.status_code, 400, response.content)

    def test_curriculum_reorder_requires_complete_unique_item_list(self):
        self.client.force_authenticate(self.admin)
        first_module = CourseModule.objects.create(
            course=self.draft_course, title="First module", position=1
        )
        second_module = CourseModule.objects.create(
            course=self.draft_course, title="Second module", position=2
        )
        response = self.client.post(
            "/api/v1/course-modules/reorder/",
            {
                "parent_id": str(self.draft_course.id),
                "ids": [str(first_module.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        first_module.refresh_from_db()
        second_module.refresh_from_db()
        self.assertEqual((first_module.position, second_module.position), (1, 2))

        response = self.client.post(
            "/api/v1/course-modules/reorder/",
            {
                "parent_id": str(self.draft_course.id),
                "ids": [str(first_module.id), str(first_module.id)],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_curriculum_visibility_is_separate_from_soft_archive(self):
        visible_module = CourseModule.objects.create(
            course=self.published_course,
            title="Visible module",
            position=1,
        )
        hidden_module = CourseModule.objects.create(
            course=self.published_course,
            title="Hidden module",
            position=2,
            is_visible=False,
        )
        Unit.objects.create(
            module=hidden_module,
            title="Hidden topic",
            position=1,
        )
        self.client.force_authenticate(None)
        response = self.client.get(
            "/api/v1/course-modules/",
            {"course": str(self.published_course.id)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            [item["id"] for item in response.json()["results"]],
            [str(visible_module.id)],
        )
        response = self.client.get(
            "/api/v1/course-units/",
            {"module": str(hidden_module.id)},
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["results"], [])

        self.client.force_authenticate(self.admin)
        response = self.client.patch(
            f"/api/v1/course-modules/{visible_module.id}/",
            {"is_visible": False},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        visible_module.refresh_from_db()
        self.assertFalse(visible_module.is_visible)
        self.assertTrue(visible_module.is_active)

        response = self.client.delete(f"/api/v1/course-modules/{hidden_module.id}/")
        self.assertEqual(response.status_code, 204, response.content)
        hidden_module.refresh_from_db()
        self.assertFalse(hidden_module.is_active)
        self.assertFalse(hidden_module.is_visible)

        response = self.client.patch(
            f"/api/v1/course-modules/{hidden_module.id}/",
            {"is_active": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        hidden_module.refresh_from_db()
        self.assertFalse(hidden_module.is_active)

    def test_course_author_assignment_is_unit_scoped_and_audited(self):
        self.client.force_authenticate(self.hod)
        response = self.client.post(
            "/api/v1/course-assignments/",
            {
                "course": str(self.published_course.id),
                "teacher": str(self.teacher.id),
                "can_edit_content": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        assignment = CourseAssignment.objects.get(
            course=self.published_course, teacher=self.teacher
        )
        self.assertTrue(assignment.can_edit_content)
        self.assertTrue(
            AuditLog.objects.filter(action="course_teacher_created").exists()
        )

        other_unit = BusinessUnit.objects.create(
            code="OTHER",
            name="Other Institute",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        other_teacher = create_role_user(
            "other-unit-teacher",
            role=Role.TEACHER,
            unit=other_unit,
        )
        response = self.client.post(
            "/api/v1/course-assignments/",
            {
                "course": str(self.published_course.id),
                "teacher": str(other_teacher.id),
                "can_edit_content": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(
            CourseAssignment.objects.filter(
                course=self.published_course, teacher=other_teacher
            ).exists()
        )

    def test_course_update_rejects_stale_version(self):
        self.client.force_authenticate(self.hod)
        course = Course.objects.create(
            department=self.department,
            created_by=self.hod,
            title="Versioned course",
            code="VER-1",
            status=Course.Status.DRAFT,
        )

        response = self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"title": "Updated title", "version": course.version},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        stale_version = course.version
        course.refresh_from_db()
        response = self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"title": "Another update", "version": stale_version},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("version", response.json()["fields"])

    def test_course_update_requires_version_and_locks_identity_after_classes_exist(
        self,
    ):
        self.client.force_authenticate(self.hod)
        course = Course.objects.create(
            department=self.department,
            created_by=self.hod,
            title="Versioned course",
            code="LOCK-1",
        )

        other_unit = BusinessUnit.objects.create(
            code="OTHER",
            name="Other Institute",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        other_unit_department = Department.objects.create(
            unit=other_unit,
            campus=self.department.campus,
            name="Other department",
            code="OTH",
        )
        self.client.force_authenticate(self.admin)
        cross_unit_move = self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"department": str(other_unit_department.id), "version": course.version},
            format="json",
        )
        self.assertEqual(cross_unit_move.status_code, 400, cross_unit_move.content)
        self.assertIn("department", cross_unit_move.json()["fields"])
        self.assertIn(
            "business unit",
            str(cross_unit_move.json()["fields"]["department"]).lower(),
        )

        self.client.force_authenticate(self.hod)
        missing_version = self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"title": "Missing version"},
            format="json",
        )
        self.assertEqual(missing_version.status_code, 400, missing_version.content)
        self.assertIn("version", missing_version.json()["fields"])

        ClassGroup.objects.create(
            course=course,
            name="Locked course class",
            code="LOCK-CLASS-1",
        )
        locked_code = self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"code": "LOCK-2", "version": course.version},
            format="json",
        )
        self.assertEqual(locked_code.status_code, 400, locked_code.content)
        self.assertIn("code", locked_code.json()["fields"])
        course.refresh_from_db()
        self.assertEqual(course.code, "LOCK-1")

        editable_title = self.client.patch(
            f"/api/v1/courses/{course.slug}/",
            {"title": "Updated after class creation", "version": course.version},
            format="json",
        )
        self.assertEqual(editable_title.status_code, 200, editable_title.content)
        self.assertEqual(editable_title.json()["version"], course.version + 1)

    def test_unit_manager_can_move_unblocked_course_within_unit(self):
        manager = create_role_user(
            "move-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        course = self.create_course_for_department_move("MOVE-OK")

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 200, response.content)
        course.refresh_from_db()
        self.assertEqual(course.department, self.other_department)
        self.assertEqual(course.unit, self.unit)

    def test_class_blocks_course_department_move(self):
        manager = create_role_user(
            "class-block-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        course = self.create_course_for_department_move("MOVE-CLASS")
        ClassGroup.objects.create(
            course=course,
            name="Existing class",
            code="MOVE-CLASS-GROUP",
        )

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("classes", str(response.json()["fields"]["department"]).lower())

    def test_enrollment_blocks_course_department_move(self):
        manager = create_role_user(
            "enrollment-block-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        course = self.create_course_for_department_move("MOVE-ENROLL")
        Enrollment.objects.create(
            student=Student.objects.get(user=self.student),
            course=course,
        )

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(
            "enrollments",
            str(response.json()["fields"]["department"]).lower(),
        )

    def test_course_access_blocks_course_department_move(self):
        manager = create_role_user(
            "access-block-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        course = self.create_course_for_department_move("MOVE-ACCESS")
        enrollment = Enrollment.objects.create(
            student=Student.objects.get(user=self.student),
            course=course,
        )
        CourseAccess.objects.create(
            student=enrollment.student,
            course=course,
            enrollment=enrollment,
        )

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 400, response.content)
        message = str(response.json()["fields"]["department"]).lower()
        self.assertIn("enrollments", message)
        self.assertIn("course access rows", message)

    def test_graded_assessment_blocks_course_department_move(self):
        manager = create_role_user(
            "grade-block-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        course = self.create_course_for_department_move("MOVE-GRADE")
        template = AssessmentTemplate.objects.create(
            course=course,
            created_by=self.admin,
            title="Existing assessment",
            kind=Assessment.Kind.ASSIGNMENT,
            maximum_score="100.00",
        )
        assessment = Assessment.objects.create(template=template)
        file = StoredFile.objects.create(
            purpose=StoredFile.Purpose.SUBMISSION,
            owner_user=self.student,
            object_key=f"submission/{uuid4().hex}",
            original_name="submission.pdf",
            content_type="application/pdf",
            size_bytes=1234,
            status=StoredFile.Status.READY,
        )
        submission = Submission.objects.create(
            assessment=assessment,
            student=Student.objects.get(user=self.student),
            file=file,
        )
        enrollment = Enrollment.objects.create(
            student=submission.student,
            course=course,
        )
        Grade.objects.create(
            assessment=assessment,
            enrollment=enrollment,
            submission=submission,
            source=Grade.Source.SUBMISSION,
            score="80.00",
            graded_by=self.admin,
        )

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn(
            "assessments with submissions or grades",
            str(response.json()["fields"]["department"]).lower(),
        )

    def test_hod_cannot_move_course_department(self):
        course = self.create_course_for_department_move("MOVE-HOD")

        response = self.move_course_to_department(
            course, self.hod, self.other_department
        )

        self.assertEqual(response.status_code, 403, response.content)

    def test_program_must_match_department_after_move(self):
        manager = create_role_user(
            "program-block-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        program = Program.objects.create(
            unit=self.unit,
            department=self.department,
            name="Travel program",
            code="MOVE-PROGRAM",
        )
        course = self.create_course_for_department_move("MOVE-PROG", program=program)

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("program", response.json()["fields"])

    def test_course_department_move_audit_records_unit_actor_and_departments(self):
        manager = create_role_user(
            "audit-move-manager",
            role=Role.UNIT_MANAGER,
            unit=self.unit,
        )
        course = self.create_course_for_department_move("MOVE-AUDIT")

        response = self.move_course_to_department(
            course, manager, self.other_department
        )

        self.assertEqual(response.status_code, 200, response.content)
        audit = AuditLog.objects.get(
            action="course_department_moved",
            object_id=str(course.id),
        )
        self.assertEqual(audit.actor, manager)
        self.assertEqual(audit.unit, self.unit)
        self.assertEqual(audit.before["department"], str(self.department.id))
        self.assertEqual(audit.after["department"], str(self.other_department.id))

    def test_course_lifecycle_actions_are_versioned_audited_and_never_deleted(self):
        self.client.force_authenticate(self.hod)
        course = Course.objects.create(
            department=self.department,
            created_by=self.hod,
            title="Lifecycle course",
            code="LIFE-1",
        )
        course_url = f"/api/v1/courses/{course.slug}/"
        bypass_action = self.client.patch(
            course_url,
            {"status": Course.Status.PUBLISHED, "version": course.version},
            format="json",
        )
        self.assertEqual(bypass_action.status_code, 400, bypass_action.content)
        course.refresh_from_db()
        self.assertEqual(course.status, Course.Status.DRAFT)

        published = self.client.post(
            f"{course_url}publish/", {"version": course.version}, format="json"
        )
        self.assertEqual(published.status_code, 200, published.content)
        self.assertEqual(published.json()["status"], Course.Status.PUBLISHED)
        self.assertEqual(published.json()["version"], course.version + 1)

        current_version = published.json()["version"]
        stale_unpublish = self.client.post(
            f"{course_url}unpublish/",
            {"version": course.version},
            format="json",
        )
        self.assertEqual(stale_unpublish.status_code, 400, stale_unpublish.content)

        unpublished = self.client.post(
            f"{course_url}unpublish/",
            {"version": current_version},
            format="json",
        )
        self.assertEqual(unpublished.status_code, 200, unpublished.content)
        self.assertEqual(unpublished.json()["status"], Course.Status.DRAFT)

        current_version = unpublished.json()["version"]
        first_copy = self.client.post(
            f"{course_url}duplicate/",
            {"version": current_version},
            format="json",
        )
        second_copy = self.client.post(
            f"{course_url}duplicate/",
            {"version": current_version},
            format="json",
        )
        self.assertEqual(first_copy.status_code, 200, first_copy.content)
        self.assertEqual(second_copy.status_code, 200, second_copy.content)
        self.assertNotEqual(first_copy.json()["code"], second_copy.json()["code"])
        self.assertNotEqual(first_copy.json()["slug"], second_copy.json()["slug"])
        self.assertEqual(first_copy.json()["status"], Course.Status.DRAFT)
        self.assertEqual(
            Course.objects.filter(code__startswith="LIFE-1-COPY").count(), 2
        )

        archived = self.client.post(
            f"{course_url}archive/",
            {"version": current_version},
            format="json",
        )
        self.assertEqual(archived.status_code, 200, archived.content)
        self.assertFalse(archived.json()["is_active"])
        self.assertEqual(self.client.delete(course_url).status_code, 405)
        self.assertTrue(
            AuditLog.objects.filter(
                action="course_published",
                object_id=str(course.id),
                unit=self.unit,
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="course_unpublished",
                object_id=str(course.id),
                unit=self.unit,
            ).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="course_archived",
                object_id=str(course.id),
                unit=self.unit,
            ).exists()
        )

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


class AcademicsRoleAssignmentAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.campus = Campus.objects.create(name="Main", code="MAIN")
        self.wti = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.wti_department = Department.objects.create(
            unit=self.wti, campus=self.campus, name="Travel", code="TRV"
        )
        self.wti_other_department = Department.objects.create(
            unit=self.wti, campus=self.campus, name="Hospitality", code="HSP"
        )
        self.wta_department = Department.objects.create(
            unit=self.wta, campus=self.campus, name="Agency", code="AGY"
        )

    def create_course(self, department, creator, code, status=Course.Status.DRAFT):
        return Course.objects.create(
            department=department,
            created_by=creator,
            title=code,
            code=code,
            status=status,
        )

    def test_teacher_and_unit_manager_roles_union_their_course_scopes(self):
        user = User.objects.create_user("teacher-manager")
        RoleAssignment.objects.create(user=user, role=Role.TEACHER, unit=self.wti)
        RoleAssignment.objects.create(user=user, role=Role.UNIT_MANAGER, unit=self.wta)
        other_teacher = create_role_user(
            "other-teacher", role=Role.TEACHER, unit=self.wti
        )

        teacher_course = self.create_course(self.wti_department, user, "TEACHER-COURSE")
        unassigned_wti_course = self.create_course(
            self.wti_other_department, user, "UNASSIGNED-WTI"
        )
        manager_course = self.create_course(self.wta_department, user, "MANAGER-COURSE")
        CourseAssignment.objects.create(
            course=teacher_course, teacher=user, can_edit_content=True
        )
        CourseAssignment.objects.create(
            course=unassigned_wti_course, teacher=other_teacher
        )
        manager_assignment = CourseAssignment.objects.create(
            course=manager_course, teacher=other_teacher
        )
        inactive_teacher_module = CourseModule.objects.create(
            course=teacher_course, title="Teacher archive", position=1, is_active=False
        )
        CourseModule.objects.create(
            course=unassigned_wti_course,
            title="Out of scope",
            position=1,
            is_active=False,
        )
        inactive_manager_module = CourseModule.objects.create(
            course=manager_course, title="Manager archive", position=1, is_active=False
        )

        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/courses/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["code"] for item in response.json()["results"]},
            {teacher_course.code, manager_course.code},
        )

        response = self.client.get("/api/v1/course-assignments/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["results"]},
            {
                str(teacher_course.teacher_assignments.get(teacher=user).id),
                str(manager_assignment.id),
            },
        )

        response = self.client.get("/api/v1/course-modules/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["id"] for item in response.json()["results"]},
            {str(inactive_teacher_module.id), str(inactive_manager_module.id)},
        )

        response = self.client.post(
            "/api/v1/course-modules/",
            {"course": str(teacher_course.id), "title": "New module", "position": 2},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        response = self.client.post(
            "/api/v1/course-modules/",
            {
                "course": str(unassigned_wti_course.id),
                "title": "Unauthorized module",
                "position": 2,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        response = self.client.post(
            "/api/v1/courses/",
            {
                "department": str(self.wti_department.id),
                "title": "Unauthorized course",
                "code": "UNAUTHORIZED-COURSE",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Course.objects.filter(code="UNAUTHORIZED-COURSE").exists())

        response = self.client.post(
            "/api/v1/courses/",
            {
                "department": str(self.wta_department.id),
                "title": "Manager-created course",
                "code": "MANAGER-CREATED",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

    def test_hod_department_scope_unions_with_manager_unit_scope(self):
        user = User.objects.create_user("hod-manager")
        RoleAssignment.objects.create(user=user, role=Role.HOD, unit=self.wti)
        RoleAssignment.objects.create(user=user, role=Role.UNIT_MANAGER, unit=self.wta)
        RoleScope.objects.create(user=user, department=self.wti_department)

        hod_course = self.create_course(self.wti_department, user, "HOD-COURSE")
        out_of_scope_course = self.create_course(
            self.wti_other_department, user, "OUT-OF-SCOPE"
        )
        manager_course = self.create_course(
            self.wta_department, user, "HOD-MANAGER-WTA"
        )

        self.client.force_authenticate(user)
        response = self.client.get("/api/v1/courses/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["code"] for item in response.json()["results"]},
            {hod_course.code, manager_course.code},
        )

        response = self.client.post(
            "/api/v1/course-modules/",
            {
                "course": str(hod_course.id),
                "title": "HOD module",
                "position": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        response = self.client.post(
            "/api/v1/course-modules/",
            {
                "course": str(out_of_scope_course.id),
                "title": "Out-of-scope module",
                "position": 1,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_director_and_auditor_are_read_only(self):
        course_creator = User.objects.create_user("course-creator", role=Role.ADMIN)
        course = self.create_course(
            self.wti_department, course_creator, "READ-ONLY-COURSE"
        )

        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = create_role_user(f"read-only-{role.lower()}", role=role)
            self.client.force_authenticate(user)

            response = self.client.get("/api/v1/courses/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(
                course.code, {item["code"] for item in response.json()["results"]}
            )

            response = self.client.post(
                "/api/v1/course-modules/",
                {"course": str(course.id), "title": "Forbidden", "position": 1},
                format="json",
            )
            self.assertEqual(response.status_code, 403)


class CourseEditConcurrencyTests(TransactionTestCase):
    def setUp(self):
        campus = Campus.objects.create(name="Concurrent", code="COURSE-CONCURRENT")
        self.unit = BusinessUnit.objects.create(
            code="CCU",
            name="Course Concurrency Unit",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        self.department = Department.objects.create(
            unit=self.unit,
            campus=campus,
            name="Concurrency Department",
            code="CCU",
        )
        self.actors = (
            User.objects.create_user("course-race-admin-a", role=Role.ADMIN),
            User.objects.create_user("course-race-admin-b", role=Role.ADMIN),
        )
        self.course = Course.objects.create(
            department=self.department,
            created_by=self.actors[0],
            title="Concurrent course",
            code="CCU-101",
        )

    @postgres_only
    def test_only_one_concurrent_update_with_the_same_version_succeeds(self):
        barrier = Barrier(len(self.actors))
        course_slug = self.course.slug
        expected_version = self.course.version
        actor_ids = tuple(actor.pk for actor in self.actors)
        titles = ("Concurrent edit A", "Concurrent edit B")

        def update_course(params):
            actor_id, title = params
            close_old_connections()
            try:
                actor = User.objects.get(pk=actor_id)
                client = APIClient()
                client.force_authenticate(actor)
                barrier.wait(timeout=15)
                response = client.patch(
                    f"/api/v1/courses/{course_slug}/",
                    {"title": title, "version": expected_version},
                    format="json",
                )
                return response.status_code, response.data
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(self.actors)) as executor:
            results = list(executor.map(update_course, zip(actor_ids, titles)))

        self.assertCountEqual([status_code for status_code, _ in results], [200, 400])
        conflict = next(data for status_code, data in results if status_code == 400)
        self.assertIn("version", conflict["fields"])
        self.course.refresh_from_db()
        self.assertEqual(self.course.version, expected_version + 1)
        self.assertIn(self.course.title, titles)
