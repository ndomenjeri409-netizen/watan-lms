from datetime import date
from types import SimpleNamespace

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.enrollment.models import CourseAccess, Enrollment
from apps.org.models import BusinessUnit, Department
from apps.people.models import (
    Guardian,
    StaffProfile,
    Student,
)
from apps.people.permissions import PeopleManagementPermission
from apps.people.serializers import StudentSerializer
from apps.people.services import (
    import_student_csv,
    lookup_student_duplicate,
    make_duplicate_lookup,
)
from apps.scheduling.models import ClassGroup, ClassTeacher


class PeopleAuthorizationTests(TestCase):
    def setUp(self):
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
            unit=self.wti, name="Institute Department", code="INS"
        )
        self.wti_other_department = Department.objects.create(
            unit=self.wti, name="Other Institute Department", code="OIN"
        )
        self.wta_department = Department.objects.create(
            unit=self.wta, name="Travel Department", code="TRV"
        )
        self.wds_department = Department.objects.create(
            unit=self.wds, name="Driving Department", code="DRV"
        )
        self.admin = User.objects.create_user("people-admin", role=Role.ADMIN)
        self.teacher_manager = User.objects.create_user("teacher-manager")
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.TEACHER, unit=self.wti
        )
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.UNIT_MANAGER, unit=self.wta
        )
        self.teacher_manager.clear_role_cache()

        self.assigned_course = Course.objects.create(
            department=self.wti_department,
            created_by=self.admin,
            title="Assigned Course",
            code="INS-ASSIGNED",
        )
        self.unassigned_course = Course.objects.create(
            department=self.wti_department,
            created_by=self.admin,
            title="Unassigned Course",
            code="INS-UNASSIGNED",
        )
        self.wta_course = Course.objects.create(
            department=self.wta_department,
            created_by=self.admin,
            title="Travel Course",
            code="TRV-COURSE",
        )
        self.class_student = self._student(
            self.wti_department, "class-student", "INS-2026-0001"
        )
        self.unassigned_course_student = self._student(
            self.wti_department, "unassigned-course-student", "INS-2026-0002"
        )
        self.manager_student = self._student(
            self.wta_department, "manager-student", "TRV-2026-0001"
        )
        self.other_unit_student = self._student(
            self.wds_department, "other-unit-student", "DRV-2026-0001"
        )
        class_enrollment = self._course_access(
            self.class_student, self.assigned_course
        ).enrollment
        self._course_access(self.unassigned_course_student, self.unassigned_course)
        ClassTeacher.objects.create(
            class_group=class_enrollment.class_group,
            teacher=self.teacher_manager,
            role=ClassTeacher.Role.LEAD,
        )

    @staticmethod
    def _student(department, username, registration_number):
        student_user = User.objects.create_user(username)
        return Student.objects.create(
            user=student_user,
            department=department,
            registration_number=registration_number,
            first_name=username,
            last_name="Student",
            email=f"{username}@example.test",
            admission_year=2026,
        )

    @staticmethod
    def _course_access(student, course):
        class_group = ClassGroup.objects.create(
            course=course,
            name=f"{course.code} Access Class",
            code=f"C-{student.pk}",
        )
        enrollment = Enrollment.objects.create(
            student=student,
            course=course,
            class_group=class_group,
            status=Enrollment.Status.ACTIVE,
        )
        return CourseAccess.objects.create(
            student=student,
            course=course,
            enrollment=enrollment,
        )

    def test_teacher_and_unit_manager_scopes_union_without_cross_unit_leakage(self):
        self.assertSetEqual(
            set(
                Student.objects.for_user(self.teacher_manager).values_list(
                    "pk", flat=True
                )
            ),
            {self.class_student.pk, self.manager_student.pk},
        )

        enrolled_from_another_home_unit = self._student(
            self.wds_department,
            "cross-unit-enrollment",
            "DRV-2026-0002",
        )
        self._course_access(enrolled_from_another_home_unit, self.wta_course)
        manager_teacher_students = Student.objects.for_user(self.teacher_manager)
        self.assertSetEqual(
            set(manager_teacher_students.values_list("pk", flat=True)),
            {
                self.class_student.pk,
                self.manager_student.pk,
                enrolled_from_another_home_unit.pk,
            },
            msg=str(
                list(
                    manager_teacher_students.values_list(
                        "registration_number", "home_unit__code"
                    )
                )
            ),
        )

        wta_staff_user = User.objects.create_user("wta-staff")
        wti_staff_user = User.objects.create_user("wti-staff")
        wds_staff_user = User.objects.create_user("wds-staff")
        wta_staff = StaffProfile.objects.create(
            user=wta_staff_user, department=self.wta_department
        )
        StaffProfile.objects.create(user=wti_staff_user, department=self.wti_department)
        StaffProfile.objects.create(user=wds_staff_user, department=self.wds_department)
        self.assertSetEqual(
            set(
                StaffProfile.objects.for_user(self.teacher_manager).values_list(
                    "pk", flat=True
                )
            ),
            {wta_staff.pk},
        )

        wta_guardian = Guardian.objects.create(
            student=self.manager_student,
            full_name="WTA Guardian",
            relationship="Parent",
        )
        Guardian.objects.create(
            student=self.class_student,
            full_name="WTI Guardian",
            relationship="Parent",
        )
        self.assertSetEqual(
            set(
                Guardian.objects.for_user(self.teacher_manager).values_list(
                    "pk", flat=True
                )
            ),
            {wta_guardian.pk},
        )

    def test_hod_scope_is_limited_to_assigned_departments(self):
        hod = User.objects.create_user("scoped-hod", role=Role.HOD, unit=self.wti)
        RoleScope.objects.create(user=hod, department=self.wti_department)
        scoped_student = self._student(
            self.wti_department, "scoped-hod-student", "INS-2026-0003"
        )
        self._course_access(scoped_student, self.unassigned_course)
        unscoped_student = self._student(
            self.wti_other_department, "unscoped-hod-student", "OIN-2026-0001"
        )

        self.assertSetEqual(
            set(Student.objects.for_user(hod).values_list("pk", flat=True)),
            {
                self.class_student.pk,
                self.unassigned_course_student.pk,
                scoped_student.pk,
            },
        )
        self.assertNotIn(
            unscoped_student.pk,
            Student.objects.for_user(hod).values_list("pk", flat=True),
        )

    def test_directors_and_auditors_are_read_only(self):
        permission = PeopleManagementPermission()
        view = SimpleNamespace(queryset=Student.objects.all())

        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = User.objects.create_user(f"read-only-{role}", role=role)
            self.assertTrue(
                permission.has_permission(
                    SimpleNamespace(user=user, method="GET"), view
                )
            )
            self.assertFalse(
                permission.has_permission(
                    SimpleNamespace(user=user, method="POST"), view
                )
            )

    def test_student_write_endpoint_role_matrix(self):
        teacher = User.objects.create_user(
            "write-matrix-teacher", role=Role.TEACHER, unit=self.wti
        )
        bursar = User.objects.create_user(
            "write-matrix-bursar", role=Role.BURSAR, unit=self.wti
        )
        cashier = User.objects.create_user(
            "write-matrix-cashier", role=Role.CASHIER, unit=self.wti
        )
        director = User.objects.create_user("write-matrix-director", role=Role.DIRECTOR)
        auditor = User.objects.create_user("write-matrix-auditor", role=Role.AUDITOR)

        write_endpoints = (
            ("/api/v1/students/", "json"),
            ("/api/v1/students/duplicate-lookup/", "json"),
            ("/api/v1/students/import/", "multipart"),
            ("/api/v1/students/enroll-in-unit/", "json"),
            (f"/api/v1/students/{self.manager_student.pk}/transfer/", "json"),
            (f"/api/v1/students/{self.manager_student.pk}/change-status/", "json"),
            (f"/api/v1/students/{self.manager_student.pk}/invite/", "json"),
        )
        actors = (
            (None, 401),
            (teacher, 403),
            (bursar, 403),
            (cashier, 403),
            (director, 403),
            (auditor, 403),
            (self.manager_student.user, 403),
        )
        for actor, expected_status in actors:
            for path, request_format in write_endpoints:
                actor_label = actor.firebase_uid if actor else "anonymous"
                with self.subTest(actor=actor_label, path=path):
                    client = APIClient()
                    client.force_authenticate(actor)
                    response = client.post(path, {}, format=request_format)
                    self.assertEqual(
                        response.status_code, expected_status, response.data
                    )

    def test_guardian_changes_require_scope_or_student_ownership(self):
        permission = PeopleManagementPermission()
        guardian = Guardian.objects.create(
            student=self.manager_student,
            full_name="Manager Guardian",
            relationship="Parent",
        )
        other_guardian = Guardian.objects.create(
            student=self.class_student,
            full_name="Other Guardian",
            relationship="Parent",
        )
        view = SimpleNamespace(queryset=Guardian.objects.all())
        request = SimpleNamespace(user=self.teacher_manager, method="PATCH")

        self.assertTrue(permission.has_permission(request, view))
        self.assertTrue(permission.has_object_permission(request, view, guardian))
        self.assertFalse(
            permission.has_object_permission(request, view, other_guardian)
        )

    def test_student_sensitive_fields_are_hidden_from_cashiers(self):
        self.manager_student.date_of_birth = date(2004, 5, 6)
        self.manager_student.national_id = "ID-RESTRICTED"
        self.manager_student.save(update_fields=("date_of_birth", "national_id"))
        cashier = User.objects.create_user(
            "restricted-cashier", role=Role.CASHIER, unit=self.wta
        )
        bursar = User.objects.create_user(
            "restricted-bursar", role=Role.BURSAR, unit=self.wta
        )

        cashier_data = StudentSerializer(
            self.manager_student, context={"request": SimpleNamespace(user=cashier)}
        ).data
        bursar_data = StudentSerializer(
            self.manager_student, context={"request": SimpleNamespace(user=bursar)}
        ).data

        self.assertNotIn("date_of_birth", cashier_data)
        self.assertNotIn("national_id", cashier_data)
        self.assertEqual(bursar_data["date_of_birth"], "2004-05-06")
        self.assertEqual(bursar_data["national_id"], "ID-RESTRICTED")

    def test_restricted_fields_follow_manager_scope_for_multi_role_users(self):
        for student in (self.class_student, self.manager_student):
            student.date_of_birth = date(2004, 5, 6)
            student.national_id = f"ID-{student.registration_number}"
            student.save(update_fields=("date_of_birth", "national_id"))

        wti_teacher_wta_manager = self.teacher_manager
        wti_student_data = StudentSerializer(
            self.class_student,
            context={"request": SimpleNamespace(user=wti_teacher_wta_manager)},
        ).data
        wta_student_data = StudentSerializer(
            self.manager_student,
            context={"request": SimpleNamespace(user=wti_teacher_wta_manager)},
        ).data

        self.assertNotIn("date_of_birth", wti_student_data)
        self.assertNotIn("national_id", wti_student_data)
        self.assertEqual(wta_student_data["date_of_birth"], "2004-05-06")
        self.assertEqual(
            wta_student_data["national_id"],
            f"ID-{self.manager_student.registration_number}",
        )

    def test_exact_duplicate_lookup_is_minimal_and_single_use(self):
        self.manager_student.phone = "+254700000001"
        self.manager_student.national_id = "ID-PRIVATE"
        self.manager_student.save(update_fields=("phone", "national_id"))
        token = make_duplicate_lookup(
            self.teacher_manager,
            self.wta,
            Student.objects.filter(pk=self.manager_student.pk),
        )

        result = lookup_student_duplicate(
            actor=self.teacher_manager, token=token, phone="+254700000001"
        )

        self.assertEqual(
            set(result[0]),
            {"name", "home_unit", "registration_number", "enrollment_token"},
        )
        self.assertEqual(result[0]["home_unit"], self.wta.code)
        with self.assertRaises(ValidationError):
            lookup_student_duplicate(
                actor=self.teacher_manager, token=token, phone="+254700000001"
            )
        self.wta_course.status = Course.Status.PUBLISHED
        self.wta_course.save(update_fields=("status", "updated_at"))
        class_group = ClassGroup.objects.create(
            course=self.wta_course,
            name="Duplicate Enrollment Class",
            code="DUPLICATE-ENROLL",
            status=ClassGroup.Status.OPEN,
        )
        client = APIClient()
        client.force_authenticate(self.teacher_manager)
        enrollment_response = client.post(
            "/api/v1/students/enroll-in-unit/",
            {
                "class_group": str(class_group.pk),
                "enrollment_token": result[0]["enrollment_token"],
            },
            format="json",
        )
        self.assertEqual(enrollment_response.status_code, 201, enrollment_response.data)
        self.assertEqual(
            enrollment_response.data["student"], str(self.manager_student.pk)
        )
        self.assertEqual(enrollment_response.data["status"], Enrollment.Status.ACTIVE)
        reused_token = client.post(
            "/api/v1/students/enroll-in-unit/",
            {
                "class_group": str(class_group.pk),
                "enrollment_token": result[0]["enrollment_token"],
            },
            format="json",
        )
        self.assertEqual(reused_token.status_code, 400, reused_token.data)

    def test_transfer_changes_home_unit_without_changing_registration_number(self):
        registration_number = self.manager_student.registration_number
        client = APIClient()
        client.force_authenticate(self.teacher_manager)
        wrong_unit_manager_response = client.post(
            f"/api/v1/students/{self.manager_student.pk}/transfer/",
            {"home_unit": str(self.wti.pk)},
            format="json",
        )
        self.assertEqual(wrong_unit_manager_response.status_code, 403)

        target_unit_manager = User.objects.create_user(
            "transfer-target-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        client.force_authenticate(target_unit_manager)
        transfer_response = client.post(
            f"/api/v1/students/{self.manager_student.pk}/transfer/",
            {"home_unit": str(self.wti.pk)},
            format="json",
        )
        self.assertEqual(transfer_response.status_code, 200, transfer_response.data)
        transferred = Student.objects.get(pk=self.manager_student.pk)

        self.assertEqual(transferred.home_unit_id, self.wti.pk)
        self.assertEqual(transferred.registration_number, registration_number)
        self.assertTrue(
            AuditLog.objects.filter(
                action="student_transferred", object_id=str(transferred.pk)
            ).exists()
        )
        with self.assertRaises(DjangoValidationError):
            Student.objects.filter(pk=transferred.pk).update(home_unit=self.wta)

    def test_status_endpoint_is_scoped_and_audited(self):
        out_of_scope_manager = User.objects.create_user(
            "status-out-of-scope-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        client = APIClient()
        client.force_authenticate(out_of_scope_manager)
        response = client.post(
            f"/api/v1/students/{self.manager_student.pk}/change-status/",
            {"status": Student.Status.SUSPENDED, "reason": "Out of scope attempt"},
            format="json",
        )
        self.assertEqual(response.status_code, 404)

        client.force_authenticate(self.teacher_manager)
        response = client.post(
            f"/api/v1/students/{self.manager_student.pk}/change-status/",
            {"status": Student.Status.SUSPENDED, "reason": "Status review"},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.manager_student.refresh_from_db()
        self.assertEqual(self.manager_student.status, Student.Status.SUSPENDED)
        self.assertTrue(
            AuditLog.objects.filter(
                action="student_status_changed",
                actor=self.teacher_manager,
                object_id=str(self.manager_student.pk),
            ).exists()
        )

    def test_csv_import_registers_valid_rows_and_reports_invalid_rows(self):
        manager = User.objects.create_user(
            "csv-import-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        self.assigned_course.status = Course.Status.PUBLISHED
        self.assigned_course.save(update_fields=("status", "updated_at"))
        ClassGroup.objects.create(
            course=self.assigned_course,
            name="Import Class",
            code="IMPORT-CLASS",
            status=ClassGroup.Status.OPEN,
        )
        upload = SimpleUploadedFile(
            "students.csv",
            b"unit_code,class_code,first_name,last_name,phone\n"
            b"WTI,IMPORT-CLASS,New,Student,+254700000002\n"
            b"WTI,UNKNOWN,Invalid,Student,+254700000003\n",
            content_type="text/csv",
        )

        result = import_student_csv(upload, SimpleNamespace(user=manager))

        self.assertEqual(result["created"], 1)
        self.assertEqual(len(result["row_errors"]), 1)
        self.assertEqual(result["row_errors"][0]["row"], 3)
        student = Student.objects.get(phone="+254700000002")
        self.assertEqual(student.home_unit_id, self.wti.pk)
        self.assertEqual(student.enrollments.get().status, Enrollment.Status.ACTIVE)

    def test_registration_api_creates_student_and_active_class_enrollment(self):
        manager = User.objects.create_user(
            "registration-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        self.assigned_course.status = Course.Status.PUBLISHED
        self.assigned_course.save(update_fields=("status", "updated_at"))
        class_group = ClassGroup.objects.create(
            course=self.assigned_course,
            name="Registration Class",
            code="REGISTRATION-CLASS",
            status=ClassGroup.Status.OPEN,
        )
        client = APIClient()
        client.force_authenticate(manager)

        response = client.post(
            "/api/v1/students/",
            {
                "unit": str(self.wti.pk),
                "class_group": str(class_group.pk),
                "first_name": "New",
                "last_name": "Learner",
                "phone": "+254700000004",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)
        student = Student.objects.get(pk=response.data["id"])
        self.assertEqual(student.home_unit_id, self.wti.pk)
        self.assertEqual(student.account_status, Student.AccountStatus.NONE)
        self.assertEqual(student.enrollments.get().class_group_id, class_group.pk)

    def test_registration_api_rejects_manager_outside_target_unit(self):
        manager = User.objects.create_user(
            "wrong-unit-registration-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        self.wta_course.status = Course.Status.PUBLISHED
        self.wta_course.save(update_fields=("status", "updated_at"))
        class_group = ClassGroup.objects.create(
            course=self.wta_course,
            name="Wrong Unit Registration Class",
            code="WRONG-UNIT-REG",
            status=ClassGroup.Status.OPEN,
        )
        client = APIClient()
        client.force_authenticate(manager)

        response = client.post(
            "/api/v1/students/",
            {
                "unit": str(self.wta.pk),
                "class_group": str(class_group.pk),
                "first_name": "Out",
                "last_name": "OfScope",
                "phone": "+254700000099",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn("unit", response.data["fields"])
        self.assertFalse(Student.objects.filter(phone="+254700000099").exists())

    def test_cross_unit_duplicate_api_returns_only_exact_lookup_token(self):
        manager = User.objects.create_user(
            "cross-duplicate-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        self.manager_student.phone = "+254700000005"
        self.manager_student.save(update_fields=("phone",))
        self.assigned_course.status = Course.Status.PUBLISHED
        self.assigned_course.save(update_fields=("status", "updated_at"))
        class_group = ClassGroup.objects.create(
            course=self.assigned_course,
            name="Duplicate Class",
            code="DUPLICATE-CLASS",
            status=ClassGroup.Status.OPEN,
        )
        client = APIClient()
        client.force_authenticate(manager)

        response = client.post(
            "/api/v1/students/",
            {
                "unit": str(self.wti.pk),
                "class_group": str(class_group.pk),
                "first_name": "Another",
                "last_name": "Learner",
                "phone": "+254700000005",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 409, response.data)
        self.assertTrue(response.data["requires_exact_lookup"])
        self.assertNotIn("name", response.data)
        lookup = client.post(
            "/api/v1/students/duplicate-lookup/",
            {"token": response.data["lookup_token"], "phone": "+254700000005"},
            format="json",
        )
        self.assertEqual(lookup.status_code, 200, lookup.data)
        self.assertEqual(
            set(lookup.data["matches"][0]),
            {"name", "home_unit", "registration_number", "enrollment_token"},
        )

    def test_csv_import_endpoint_registers_in_the_managers_unit(self):
        manager = User.objects.create_user(
            "csv-endpoint-manager", role=Role.UNIT_MANAGER, unit=self.wti
        )
        self.assigned_course.status = Course.Status.PUBLISHED
        self.assigned_course.save(update_fields=("status", "updated_at"))
        class_group = self.class_student.enrollments.get().class_group
        class_group.status = ClassGroup.Status.OPEN
        class_group.save(update_fields=("status", "updated_at"))
        csv_content = (
            "unit_code,class_code,first_name,last_name,phone\n"
            f"WTI,{class_group.code},New,Imported,+254700000098\n"
        ).encode()
        upload = SimpleUploadedFile(
            "students.csv",
            csv_content,
            content_type="text/csv",
        )
        client = APIClient()
        client.force_authenticate(manager)

        response = client.post(
            "/api/v1/students/import/", {"file": upload}, format="multipart"
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["created"], 1)
        imported = Student.objects.get(phone="+254700000098")
        self.assertEqual(imported.home_unit_id, self.wti.pk)
