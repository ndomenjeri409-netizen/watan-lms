from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import close_old_connections
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course, CourseAssignment
from apps.accounts import authentication
from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.enrollment.models import Application, CourseAccess, Enrollment
from apps.enrollment.permissions import ApplicationPermission, EnrollmentPermission
from apps.org.models import BusinessUnit, Campus, Department
from apps.people.models import (
    Student,
    allocate_registration_number,
    format_registration_number,
)
from apps.scheduling.models import ClassGroup
from tests.helpers import create_role_user, postgres_only


class EnrollmentFlowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department = Department.objects.create(
            unit=unit, campus=campus, name="Travel", code="TRV"
        )
        self.other_department = Department.objects.create(
            unit=unit, campus=campus, name="Hospitality", code="HSP"
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
            "phone": "+254700000000",
            "statement": "I want to study travel operations.",
        }

    def test_public_apply_without_email_and_staff_invite_student_access(self):
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
            patch("apps.accounts.authentication._ensure_firebase") as ensure_firebase,
            patch("apps.accounts.authentication.fb_auth.create_user") as create_user,
        ):
            response = self.client.post(
                f"/api/v1/applications/{application.id}/approve/", {}, format="json"
            )
        ensure_firebase.assert_not_called()
        create_user.assert_not_called()
        self.assertEqual(response.status_code, 200)

        student = Student.objects.get(pk=response.json()["student"]["id"])
        enrollment = Enrollment.objects.get(student=student, course=self.course)
        application.refresh_from_db()
        self.assertEqual(application.status, Application.Status.APPROVED)
        self.assertEqual(enrollment.status, Enrollment.Status.APPROVED)
        self.assertIsNone(enrollment.class_group_id)
        self.assertFalse(CourseAccess.objects.filter(student=student).exists())
        self.assertEqual(student.email, "")
        self.assertIsNone(student.user_id)
        self.assertEqual(student.account_status, Student.AccountStatus.NONE)
        self.assertEqual(
            student.registration_number,
            f"WTI/TRV/{timezone.localdate().year}/0001",
        )

        self.client.force_authenticate(self.hod)
        response = self.client.post(
            f"/api/v1/students/{student.id}/invite/", {}, format="json"
        )
        self.assertEqual(response.status_code, 400)
        student.refresh_from_db()
        self.assertIsNone(student.user_id)
        self.assertEqual(student.account_status, Student.AccountStatus.NONE)

        with (
            patch("apps.people.services.authentication._ensure_firebase"),
            patch("apps.people.services.authentication.verify_revoked_token"),
            patch(
                "apps.people.services.authentication.fb_auth.create_user",
                return_value=SimpleNamespace(uid="new-student"),
            ),
        ):
            response = self.client.post(
                f"/api/v1/students/{student.id}/invite/",
                {"email": "amina@example.test"},
                format="json",
            )
        self.assertEqual(response.status_code, 200)
        student.refresh_from_db()
        self.assertEqual(student.email, "amina@example.test")
        self.assertEqual(student.user.role, Role.STUDENT)
        self.assertEqual(student.account_status, Student.AccountStatus.INVITED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="student_invited", object_id=str(student.id)
            ).exists()
        )

        request = RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer token")
        with (
            patch("apps.accounts.authentication._ensure_firebase"),
            patch(
                "apps.accounts.authentication.fb_auth.verify_id_token",
                return_value={"uid": "new-student"},
            ),
        ):
            authenticated_user, _ = (
                authentication.FirebaseAuthentication().authenticate(request)
            )
        self.assertEqual(authenticated_user.pk, student.user_id)
        student.refresh_from_db()
        self.assertEqual(student.account_status, Student.AccountStatus.ACTIVE)

        class_group = ClassGroup.objects.create(
            course=self.course,
            name="Travel cohort",
            code="TRV-101-ACTIVE",
            capacity=1,
        )
        response = self.client.post(
            f"/api/v1/enrollments/{enrollment.id}/transition/",
            {
                "status": Enrollment.Status.ACTIVE,
                "class_group": str(class_group.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        enrollment.refresh_from_db()
        self.assertEqual(enrollment.status, Enrollment.Status.ACTIVE)
        self.assertEqual(enrollment.class_group_id, class_group.id)
        access = CourseAccess.objects.get(student=student, course=self.course)
        self.assertTrue(access.is_active)
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

    def test_enrollment_activation_requires_matching_class_and_capacity(self):
        response = self.client.post(
            "/api/v1/applications/", self.application_data, format="json"
        )
        application = Application.objects.get(pk=response.json()["id"])
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f"/api/v1/applications/{application.id}/approve/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        first_enrollment = Enrollment.objects.get(
            student_id=response.json()["student"]["id"]
        )
        self.assertEqual(first_enrollment.status, Enrollment.Status.APPROVED)

        other_course = Course.objects.create(
            department=self.department,
            created_by=self.admin,
            title="Another course",
            code="TRV-102",
        )
        wrong_class = ClassGroup.objects.create(
            course=other_course,
            name="Wrong course class",
            code="TRV-102-WRONG",
        )
        response = self.client.post(
            f"/api/v1/enrollments/{first_enrollment.id}/transition/",
            {
                "status": Enrollment.Status.ACTIVE,
                "class_group": str(wrong_class.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

        cancelled_class = ClassGroup.objects.create(
            course=self.course,
            name="Cancelled class",
            code="TRV-101-CANCELLED",
            status=ClassGroup.Status.CANCELLED,
        )
        response = self.client.post(
            f"/api/v1/enrollments/{first_enrollment.id}/transition/",
            {
                "status": Enrollment.Status.ACTIVE,
                "class_group": str(cancelled_class.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

        class_group = ClassGroup.objects.create(
            course=self.course,
            name="Limited class",
            code="TRV-101-LIMITED",
            capacity=1,
        )
        response = self.client.post(
            f"/api/v1/enrollments/{first_enrollment.id}/transition/",
            {"status": Enrollment.Status.ACTIVE},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(
            f"/api/v1/enrollments/{first_enrollment.id}/transition/",
            {
                "status": Enrollment.Status.ACTIVE,
                "class_group": str(class_group.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)

        second_data = {
            **self.application_data,
            "phone": "+254700000001",
        }
        response = self.client.post("/api/v1/applications/", second_data, format="json")
        second_application = Application.objects.get(pk=response.json()["id"])
        response = self.client.post(
            f"/api/v1/applications/{second_application.id}/approve/", {}, format="json"
        )
        second_enrollment = Enrollment.objects.get(
            student_id=response.json()["student"]["id"]
        )
        response = self.client.post(
            f"/api/v1/enrollments/{second_enrollment.id}/transition/",
            {
                "status": Enrollment.Status.ACTIVE,
                "class_group": str(class_group.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        second_enrollment.refresh_from_db()
        self.assertEqual(second_enrollment.status, Enrollment.Status.APPROVED)

    def test_failed_student_invite_rolls_back_student_and_removes_firebase_user(self):
        response = self.client.post(
            "/api/v1/applications/", self.application_data, format="json"
        )
        application = Application.objects.get(pk=response.json()["id"])
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f"/api/v1/applications/{application.id}/approve/", {}, format="json"
        )
        student = Student.objects.get(pk=response.json()["student"]["id"])

        self.client.raise_request_exception = False
        with (
            patch("apps.people.services.authentication._ensure_firebase"),
            patch("apps.people.services.authentication.verify_revoked_token"),
            patch(
                "apps.people.services.authentication.fb_auth.create_user",
                return_value=SimpleNamespace(uid="failed-student"),
            ),
            patch(
                "apps.people.services.authentication.fb_auth.delete_user"
            ) as delete_user,
            patch(
                "apps.people.services.record_audit",
                side_effect=RuntimeError("audit write failed"),
            ),
        ):
            response = self.client.post(
                f"/api/v1/students/{student.id}/invite/",
                {"email": "amina@example.test"},
                format="json",
            )

        self.assertEqual(response.status_code, 500)
        delete_user.assert_called_once_with("failed-student")
        student.refresh_from_db()
        self.assertIsNone(student.user_id)
        self.assertEqual(student.email, "")
        self.assertEqual(student.account_status, Student.AccountStatus.NONE)
        self.assertFalse(User.objects.filter(firebase_uid="failed-student").exists())

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

    def test_registration_numbers_use_the_approved_unit_department_format(self):
        ict = Department.objects.create(
            unit=self.department.unit, name="ICT", code="ICT"
        )
        self.assertEqual(
            format_registration_number(self.department.unit, ict, 2026, 1),
            "WTI/ICT/2026/0001",
        )

    def test_registration_sequence_is_scoped_by_unit_department_and_year(self):
        self.assertEqual(
            allocate_registration_number(
                self.department.unit, 2026, department=self.department
            ),
            "WTI/TRV/2026/0001",
        )
        self.assertEqual(
            allocate_registration_number(
                self.department.unit, 2026, department=self.department
            ),
            "WTI/TRV/2026/0002",
        )
        self.assertEqual(
            allocate_registration_number(
                self.department.unit, 2027, department=self.department
            ),
            "WTI/TRV/2027/0001",
        )
        self.assertEqual(
            allocate_registration_number(
                self.department.unit, 2026, department=self.other_department
            ),
            "WTI/HSP/2026/0001",
        )

    def test_unit_without_department_uses_its_own_sequence(self):
        self.assertEqual(
            allocate_registration_number(self.department.unit, 2026),
            "WTI/2026/0001",
        )
        self.assertEqual(
            allocate_registration_number(self.department.unit, 2026),
            "WTI/2026/0002",
        )

    def test_student_registration_number_cannot_be_changed(self):
        student = Student.objects.create(
            department=self.department,
            registration_number="WTI/TRV/2026/0001",
            first_name="Amina",
            last_name="Njeri",
            email="amina@example.test",
            admission_year=2026,
        )
        student.registration_number = "WTI/TRV/2026/0002"
        with self.assertRaises(ValidationError):
            student.save()
        with self.assertRaises(ValidationError):
            Student.objects.filter(pk=student.pk).update(
                registration_number="WTI/TRV/2026/0002"
            )

    def test_registration_number_report_does_not_change_unparseable_numbers(self):
        student = Student.objects.create(
            department=self.department,
            registration_number="legacy-number-needs-review",
            first_name="Amina",
            last_name="Njeri",
            email="amina@example.test",
            admission_year=2026,
        )
        output = StringIO()
        call_command("report_registration_numbers", stdout=output)

        self.assertIn("legacy-number-needs-review", output.getvalue())
        student.refresh_from_db()
        self.assertEqual(student.registration_number, "legacy-number-needs-review")


class RegistrationSequenceConcurrencyTests(TransactionTestCase):
    def setUp(self):
        campus = Campus.objects.create(name="Concurrent", code="CONCURRENT")
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department = Department.objects.create(
            unit=unit, campus=campus, name="Concurrent", code="CON"
        )

    @postgres_only
    def test_concurrent_allocations_are_distinct(self):
        worker_count = 6
        barrier = Barrier(worker_count)
        department_id = self.department.pk

        def allocate():
            close_old_connections()
            try:
                from apps.org.models import Department

                department = Department.objects.select_related("unit").get(
                    pk=department_id
                )
                barrier.wait(timeout=15)
                return allocate_registration_number(
                    department.unit, 2026, department=department
                )
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            numbers = list(executor.map(lambda _: allocate(), range(worker_count)))

        self.assertEqual(len(set(numbers)), worker_count)
        self.assertEqual(
            sorted(int(number.rsplit("/", 1)[1]) for number in numbers),
            list(range(1, worker_count + 1)),
        )


class EnrollmentAuthorizationTests(TestCase):
    def setUp(self):
        campus = Campus.objects.create(name="Authorization", code="AUTH")
        self.wti = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.wta = BusinessUnit.objects.create(
            code="WTA", name="Watan Travel Agency", kind=BusinessUnit.Kind.TRAINING
        )
        self.wds = BusinessUnit.objects.create(
            code="WDS", name="Watan Driving School", kind=BusinessUnit.Kind.DRIVING
        )
        self.wti_department = Department.objects.create(
            unit=self.wti, campus=campus, name="Institute", code="INS"
        )
        self.wti_other_department = Department.objects.create(
            unit=self.wti, campus=campus, name="Other Institute", code="OIN"
        )
        self.wta_department = Department.objects.create(
            unit=self.wta, campus=campus, name="Travel", code="TRV"
        )
        self.wds_department = Department.objects.create(
            unit=self.wds, campus=campus, name="Driving", code="DRV"
        )

        self.admin = User.objects.create_user("enrollment-admin", role=Role.ADMIN)
        self.teacher_manager = User.objects.create_user("enrollment-teacher-manager")
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.TEACHER, unit=self.wti
        )
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.UNIT_MANAGER, unit=self.wta
        )
        self.teacher_manager.clear_role_cache()

        self.hod = User.objects.create_user(
            "enrollment-hod", role=Role.HOD, unit=self.wti
        )
        RoleScope.objects.create(user=self.hod, department=self.wti_department)

        self.wti_records = self._records(self.wti_department, "WTI-1")
        self.wti_other_records = self._records(self.wti_other_department, "WTI-2")
        self.wta_records = self._records(self.wta_department, "WTA-1")
        self.wds_records = self._records(self.wds_department, "WDS-1")
        CourseAssignment.objects.create(
            unit=self.wti,
            course=self.wti_records["course"],
            teacher=self.teacher_manager,
            can_edit_content=True,
        )

    def _records(self, department, code):
        course = Course.objects.create(
            department=department,
            created_by=self.admin,
            title=f"Course {code}",
            code=code,
        )
        student_user = User.objects.create_user(f"student-{code.lower()}")
        student = Student.objects.create(
            user=student_user,
            department=department,
            registration_number=f"{department.unit.code}/{department.code}/2026/0001",
            first_name="Test",
            last_name=code,
            email=f"{code.lower()}@example.test",
            admission_year=2026,
        )
        application = Application.objects.create(
            department=department,
            course=course,
            first_name="Applicant",
            last_name=code,
            email=f"applicant-{code.lower()}@example.test",
        )
        enrollment = Enrollment.objects.create(student=student, course=course)
        access = CourseAccess.objects.create(
            student=student, course=course, enrollment=enrollment
        )
        return {
            "application": application,
            "access": access,
            "course": course,
            "enrollment": enrollment,
            "student": student,
        }

    @staticmethod
    def _ids(queryset):
        return set(queryset.values_list("pk", flat=True))

    def test_teacher_and_unit_manager_scopes_union_without_cross_unit_leaks(self):
        self.assertSetEqual(
            self._ids(Application.objects.for_user(self.teacher_manager)),
            {self.wta_records["application"].pk},
        )
        self.assertSetEqual(
            self._ids(Enrollment.objects.for_user(self.teacher_manager)),
            {
                self.wti_records["enrollment"].pk,
                self.wta_records["enrollment"].pk,
            },
        )
        self.assertSetEqual(
            self._ids(CourseAccess.objects.for_user(self.teacher_manager)),
            {self.wti_records["access"].pk, self.wta_records["access"].pk},
        )
        for records in (self.wti_other_records, self.wds_records):
            self.assertNotIn(
                records["enrollment"].pk,
                Enrollment.objects.for_user(self.teacher_manager).values_list(
                    "pk", flat=True
                ),
            )

        app_permission = ApplicationPermission()
        approve_view = SimpleNamespace(action="approve")
        app_request = SimpleNamespace(user=self.teacher_manager, method="POST")
        self.assertTrue(app_permission.has_permission(app_request, approve_view))
        self.assertTrue(
            app_permission.has_object_permission(
                app_request, approve_view, self.wta_records["application"]
            )
        )
        self.assertFalse(
            app_permission.has_object_permission(
                app_request, approve_view, self.wti_records["application"]
            )
        )

        permission = EnrollmentPermission()
        transition_view = SimpleNamespace(action="transition")
        request = SimpleNamespace(user=self.teacher_manager, method="POST")
        self.assertTrue(permission.has_permission(request, transition_view))
        self.assertTrue(
            permission.has_object_permission(
                request, transition_view, self.wta_records["enrollment"]
            )
        )
        self.assertFalse(
            permission.has_object_permission(
                request, transition_view, self.wti_records["enrollment"]
            )
        )

    def test_hod_scope_uses_only_assigned_departments(self):
        self.assertSetEqual(
            self._ids(Application.objects.for_user(self.hod)),
            {self.wti_records["application"].pk},
        )
        self.assertSetEqual(
            self._ids(Enrollment.objects.for_user(self.hod)),
            {self.wti_records["enrollment"].pk},
        )
        self.assertSetEqual(
            self._ids(CourseAccess.objects.for_user(self.hod)),
            {self.wti_records["access"].pk},
        )

    def test_student_reads_only_own_enrollment_and_active_access(self):
        student_user = self.wti_records["student"].user
        self.assertSetEqual(
            self._ids(Enrollment.objects.for_user(student_user)),
            {self.wti_records["enrollment"].pk},
        )
        self.assertSetEqual(
            self._ids(CourseAccess.objects.for_user(student_user)),
            {self.wti_records["access"].pk},
        )
        self.assertFalse(Application.objects.for_user(student_user).exists())

    def test_directors_and_auditors_are_global_read_only(self):
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = User.objects.create_user(f"enrollment-read-only-{role}", role=role)
            self.assertSetEqual(
                self._ids(Application.objects.for_user(user)),
                {
                    self.wti_records["application"].pk,
                    self.wti_other_records["application"].pk,
                    self.wta_records["application"].pk,
                    self.wds_records["application"].pk,
                },
            )
            self.assertSetEqual(
                self._ids(Enrollment.objects.for_user(user)),
                {
                    self.wti_records["enrollment"].pk,
                    self.wti_other_records["enrollment"].pk,
                    self.wta_records["enrollment"].pk,
                    self.wds_records["enrollment"].pk,
                },
            )
            self.assertSetEqual(
                self._ids(CourseAccess.objects.for_user(user)),
                {
                    self.wti_records["access"].pk,
                    self.wti_other_records["access"].pk,
                    self.wta_records["access"].pk,
                    self.wds_records["access"].pk,
                },
            )

            app_permission = ApplicationPermission()
            self.assertTrue(
                app_permission.has_permission(
                    SimpleNamespace(user=user, method="GET"),
                    SimpleNamespace(action="list"),
                )
            )
            self.assertFalse(
                app_permission.has_permission(
                    SimpleNamespace(user=user, method="POST"),
                    SimpleNamespace(action="reject"),
                )
            )
            enrollment_permission = EnrollmentPermission()
            self.assertTrue(
                enrollment_permission.has_permission(
                    SimpleNamespace(user=user, method="GET"),
                    SimpleNamespace(action="list"),
                )
            )
            self.assertFalse(
                enrollment_permission.has_permission(
                    SimpleNamespace(user=user, method="POST"),
                    SimpleNamespace(action="transition"),
                )
            )
