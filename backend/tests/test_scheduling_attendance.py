import hashlib
from datetime import date, time, timedelta
from types import SimpleNamespace

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course, CourseAssignment
from apps.accounts.models import RoleAssignment, RoleScope, User
from apps.accounts.roles import Role
from apps.attendance.models import AttendanceRecord, AttendanceSession, QrToken
from apps.attendance.permissions import AttendancePermission
from apps.audit.models import AuditLog
from apps.enrollment.models import CourseAccess, Enrollment
from apps.org.models import AcademicPeriod, BusinessUnit, Campus, Department
from apps.people.models import Student
from apps.scheduling.models import ClassGroup, ClassTeacher, Room, TimetableSlot
from apps.scheduling.permissions import SchedulingPermission
from tests.helpers import create_role_user


class SchedulingAttendanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        unit = BusinessUnit.objects.create(
            code="WTI", name="Watan Training Institute", kind=BusinessUnit.Kind.ACADEMIC
        )
        self.department = Department.objects.create(
            unit=unit, campus=campus, name="Travel", code="TRV"
        )
        self.period = AcademicPeriod.objects.create(
            name="Travel Term",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
        )
        self.admin = User.objects.create_user("admin", role=Role.ADMIN)
        self.teacher = create_role_user("teacher", role=Role.TEACHER)
        self.student_user = User.objects.create_user("student", role=Role.STUDENT)
        self.course = Course.objects.create(
            department=self.department,
            created_by=self.admin,
            title="Travel operations",
            code="TRV-101",
            status=Course.Status.PUBLISHED,
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
        self.group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Group A",
            code="TRV-101-A",
            status=ClassGroup.Status.RUNNING,
        )
        ClassTeacher.objects.create(
            class_group=self.group,
            teacher=self.teacher,
            role=ClassTeacher.Role.LEAD,
        )
        enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            class_group=self.group,
            status=Enrollment.Status.ACTIVE,
        )
        CourseAccess.objects.create(
            student=self.student, course=self.course, enrollment=enrollment
        )

    def test_timetable_rejects_overlapping_teacher_booking(self):
        room = Room.objects.create(
            department=self.department, name="Room 1", code="R1", capacity=30
        )
        self.client.force_authenticate(self.admin)
        first = self.client.post(
            "/api/v1/timetable/",
            {
                "class_group": str(self.group.id),
                "room": str(room.id),
                "weekday": 0,
                "starts_at": "09:00:00",
                "ends_at": "10:00:00",
                "effective_from": date.today().isoformat(),
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.content)
        other_group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Group B",
            code="TRV-101-B",
        )
        ClassTeacher.objects.create(
            class_group=other_group,
            teacher=self.teacher,
            role=ClassTeacher.Role.LEAD,
        )
        conflicting = self.client.post(
            "/api/v1/timetable/",
            {
                "class_group": str(other_group.id),
                "room": None,
                "weekday": 0,
                "starts_at": "09:30:00",
                "ends_at": "10:30:00",
                "effective_from": date.today().isoformat(),
            },
            format="json",
        )
        self.assertEqual(conflicting.status_code, 400, conflicting.content)
        self.assertEqual(TimetableSlot.objects.count(), 1)

    def test_class_creation_requires_published_course_period_and_positive_capacity(
        self,
    ):
        self.client.force_authenticate(self.admin)
        payload = {
            "course": str(self.course.id),
            "lead_teacher": str(self.teacher.id),
            "academic_period": str(self.period.id),
            "name": "Cohort 2026",
            "code": "TRV-101-NEW",
            "capacity": 24,
        }
        missing_period = {**payload}
        del missing_period["academic_period"]
        response = self.client.post(
            "/api/v1/class-groups/", missing_period, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("academic_period", response.json()["fields"])

        zero_capacity = {**payload, "code": "TRV-101-ZERO", "capacity": 0}
        response = self.client.post(
            "/api/v1/class-groups/", zero_capacity, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("capacity", response.json()["fields"])

        draft_course = Course.objects.create(
            department=self.department,
            created_by=self.admin,
            title="Draft course",
            code="TRV-DRAFT",
        )
        unpublished = {**payload, "course": str(draft_course.id), "code": "TRV-101-D"}
        response = self.client.post("/api/v1/class-groups/", unpublished, format="json")
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("course", response.json()["fields"])

        response = self.client.post("/api/v1/class-groups/", payload, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["status"], ClassGroup.Status.PLANNED)
        self.assertEqual(response.json()["lead_teacher_id"], str(self.teacher.id))
        self.assertEqual(
            response.json()["lead_teacher_name"],
            self.teacher.display_name or self.teacher.email,
        )

    def test_class_creation_rejects_legacy_inactive_and_other_unit_periods(self):
        self.client.force_authenticate(self.admin)
        periods = (
            AcademicPeriod.objects.create(
                name="Legacy Period",
                starts_on=date(2026, 1, 1),
                ends_on=date(2026, 12, 31),
            ),
            AcademicPeriod.objects.create(
                name="Inactive Term",
                starts_on=date(2026, 1, 1),
                ends_on=date(2026, 12, 31),
                kind=AcademicPeriod.Kind.TERM,
                is_active=False,
            ),
        )
        other_unit = BusinessUnit.objects.create(
            code="OTHER",
            name="Other Unit",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        other_unit_period = AcademicPeriod.objects.create(
            name="Other Unit Term",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
            unit=other_unit,
        )
        payload = {
            "course": str(self.course.id),
            "lead_teacher": str(self.teacher.id),
            "name": "Invalid period cohort",
            "capacity": 24,
        }

        for index, period in enumerate((*periods, other_unit_period)):
            with self.subTest(period=period.name):
                response = self.client.post(
                    "/api/v1/class-groups/",
                    {
                        **payload,
                        "academic_period": str(period.id),
                        "code": f"TRV-101-INVALID-{index}",
                    },
                    format="json",
                )
                self.assertEqual(response.status_code, 400, response.content)
                self.assertIn("academic_period", response.json()["fields"])

    def test_academic_period_unit_cannot_conflict_with_existing_classes(self):
        self.client.force_authenticate(self.admin)
        other_unit = BusinessUnit.objects.create(
            code="OTHER",
            name="Other Unit",
            kind=BusinessUnit.Kind.ACADEMIC,
        )

        response = self.client.patch(
            f"/api/v1/academic-periods/{self.period.id}/",
            {"unit": str(other_unit.id)},
            format="json",
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("unit", response.json()["fields"])

    def test_class_status_transitions_and_cancellation_cleanup(self):
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            "/api/v1/class-groups/",
            {
                "course": str(self.course.id),
                "lead_teacher": str(self.teacher.id),
                "academic_period": str(self.period.id),
                "name": "Lifecycle cohort",
                "code": "TRV-101-LIFE",
                "capacity": 24,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        group_id = response.json()["id"]

        response = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": group_id, "title": "Too early"},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

        response = self.client.post(
            f"/api/v1/class-groups/{group_id}/transition/",
            {"status": ClassGroup.Status.RUNNING},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

        for target in (ClassGroup.Status.OPEN, ClassGroup.Status.RUNNING):
            response = self.client.post(
                f"/api/v1/class-groups/{group_id}/transition/",
                {"status": target},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.content)

        group = ClassGroup.objects.get(pk=group_id)
        session = AttendanceSession.objects.create(
            class_group=group, opened_by=self.admin, is_open=True
        )
        slot = TimetableSlot.objects.create(
            class_group=group,
            weekday=0,
            starts_at=time(9),
            ends_at=time(10),
            effective_from=date(2026, 1, 1),
        )
        response = self.client.post(
            f"/api/v1/class-groups/{group_id}/transition/",
            {"status": ClassGroup.Status.CANCELLED},
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["status"], ClassGroup.Status.CANCELLED)
        session.refresh_from_db()
        slot.refresh_from_db()
        self.assertFalse(session.is_open)
        self.assertFalse(slot.is_active)

        response = self.client.post(
            f"/api/v1/class-groups/{group_id}/transition/",
            {"status": ClassGroup.Status.OPEN},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_class_cannot_run_without_an_active_teacher_assignment(self):
        group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="No assignment",
            code="TRV-101-NO-TEACHER",
            status=ClassGroup.Status.OPEN,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.post(
            f"/api/v1/class-groups/{group.id}/transition/",
            {"status": ClassGroup.Status.RUNNING},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("status", response.json()["fields"])

    def test_class_with_active_enrollment_cannot_be_cancelled(self):
        group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Enrolled cohort",
            code="TRV-101-ENROLLED",
            status=ClassGroup.Status.OPEN,
        )
        student = Student.objects.create(
            department=self.department,
            registration_number="TRV-2026-0002",
            first_name="Sifa",
            last_name="Wanjiku",
            admission_year=2026,
        )
        Enrollment.objects.create(
            student=student,
            course=self.course,
            class_group=group,
            status=Enrollment.Status.ACTIVE,
        )
        self.client.force_authenticate(self.admin)
        response = self.client.delete(f"/api/v1/class-groups/{group.id}/")
        self.assertEqual(response.status_code, 400, response.content)
        response = self.client.post(
            f"/api/v1/class-groups/{group.id}/transition/",
            {"status": ClassGroup.Status.CANCELLED},
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(
            ClassGroup.objects.get(pk=group.pk).status, ClassGroup.Status.OPEN
        )

    def test_timetable_rejects_overlapping_room_booking(self):
        room = Room.objects.create(
            department=self.department, name="Room 1", code="R1", capacity=30
        )
        first_teacher = create_role_user("teacher-1", role=Role.TEACHER)
        second_teacher = create_role_user("teacher-2", role=Role.TEACHER)
        first_group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Group A",
            code="TRV-101-R1",
        )
        ClassTeacher.objects.create(
            class_group=first_group,
            teacher=first_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        ClassTeacher.objects.create(
            class_group=first_group,
            teacher=second_teacher,
            role=ClassTeacher.Role.ASSISTANT,
        )
        second_group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Group B",
            code="TRV-101-R2",
        )
        ClassTeacher.objects.create(
            class_group=second_group,
            teacher=second_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        self.client.force_authenticate(self.admin)
        for group, start, end in (
            (first_group, "09:00:00", "10:00:00"),
            (second_group, "09:30:00", "10:30:00"),
        ):
            response = self.client.post(
                "/api/v1/timetable/",
                {
                    "class_group": str(group.id),
                    "room": str(room.id),
                    "weekday": 0,
                    "starts_at": start,
                    "ends_at": end,
                    "effective_from": date.today().isoformat(),
                },
                format="json",
            )
            if group == first_group:
                self.assertEqual(response.status_code, 201, response.content)
            else:
                self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(TimetableSlot.objects.count(), 1)

    def test_teacher_cannot_read_other_teachers_class_group(self):
        other_teacher = create_role_user("other-teacher", role=Role.TEACHER)
        other_group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Group B",
            code="TRV-101-B",
        )
        ClassTeacher.objects.create(
            class_group=other_group,
            teacher=other_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        self.client.force_authenticate(self.teacher)
        response = self.client.get("/api/v1/class-groups/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [str(self.group.id)]
        )

    def test_class_teacher_assignment_grants_and_revokes_class_access(self):
        assistant = create_role_user("assistant-teacher", role=Role.TEACHER)
        manager = create_role_user("class-unit-manager", role=Role.UNIT_MANAGER)
        other_unit = BusinessUnit.objects.create(
            code="OTHER",
            name="Other Institute",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        out_of_unit_teacher = create_role_user(
            "out-of-unit-teacher",
            role=Role.TEACHER,
            unit=other_unit,
        )
        self.client.force_authenticate(manager)
        group_list = self.client.get("/api/v1/class-groups/")
        self.assertEqual(group_list.status_code, 200, group_list.content)
        self.assertIn(
            str(self.group.id),
            {group["id"] for group in group_list.json()["results"]},
        )
        teacher_list = self.client.get("/api/v1/users/?role=TEACHER")
        self.assertEqual(teacher_list.status_code, 200, teacher_list.content)
        self.assertIn(
            str(assistant.id),
            {teacher["id"] for teacher in teacher_list.json()["results"]},
        )
        self.assertNotIn(
            str(out_of_unit_teacher.id),
            {teacher["id"] for teacher in teacher_list.json()["results"]},
        )
        invalid = self.client.post(
            "/api/v1/class-teachers/",
            {
                "class_group": str(self.group.id),
                "teacher": str(out_of_unit_teacher.id),
                "role": ClassTeacher.Role.ASSISTANT,
            },
            format="json",
        )
        self.assertEqual(invalid.status_code, 400, invalid.content)

        response = self.client.post(
            "/api/v1/class-teachers/",
            {
                "class_group": str(self.group.id),
                "teacher": str(assistant.id),
                "role": ClassTeacher.Role.ASSISTANT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        assignment_id = response.json()["id"]

        self.client.force_authenticate(assistant)
        response = self.client.get("/api/v1/class-groups/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [str(self.group.id)]
        )
        response = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.group.id), "title": "Assistant attendance"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        self.client.force_authenticate(manager)
        response = self.client.delete(f"/api/v1/class-teachers/{assignment_id}/")
        self.assertEqual(response.status_code, 204)

        self.client.force_authenticate(assistant)
        response = self.client.get("/api/v1/class-groups/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["results"], [])
        response = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.group.id), "title": "Unassigned attendance"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_lead_teacher_can_be_reassigned_through_class_teacher_assignments(self):
        manager = create_role_user(
            "lead-change-manager", role=Role.UNIT_MANAGER, unit=self.course.unit
        )
        new_lead = create_role_user(
            "new-lead-teacher", role=Role.TEACHER, unit=self.course.unit
        )
        self.client.force_authenticate(manager)

        response = self.client.post(
            "/api/v1/class-teachers/",
            {
                "class_group": str(self.group.id),
                "teacher": str(new_lead.id),
                "role": ClassTeacher.Role.LEAD,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(
            ClassTeacher.objects.get(class_group=self.group, teacher=new_lead).role,
            ClassTeacher.Role.LEAD,
        )
        previous_lead = ClassTeacher.objects.get(
            class_group=self.group, teacher=self.teacher
        )
        self.assertEqual(previous_lead.role, ClassTeacher.Role.ASSISTANT)
        self.assertTrue(previous_lead.is_active)

        response = self.client.get(f"/api/v1/class-groups/{self.group.id}/")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json()["lead_teacher_id"], str(new_lead.id))

        response = self.client.post(
            "/api/v1/class-teachers/",
            {
                "class_group": str(self.group.id),
                "teacher": str(new_lead.id),
                "role": ClassTeacher.Role.ASSISTANT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

    def test_student_checkin_and_duplicate_conflict(self):
        session = AttendanceSession.objects.create(
            class_group=self.group, opened_by=self.teacher, title="Morning class"
        )
        raw_token = "test-qr-code"
        QrToken.objects.create(
            session=session,
            token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.client.force_authenticate(self.student_user)
        first = self.client.post(
            "/api/v1/attendance/check-in/", {"token": raw_token}, format="json"
        )
        self.assertEqual(first.status_code, 201, first.content)
        second = self.client.post(
            "/api/v1/attendance/check-in/", {"token": raw_token}, format="json"
        )
        self.assertEqual(second.status_code, 409, second.content)
        self.assertEqual(AttendanceRecord.objects.filter(session=session).count(), 1)

    def test_staff_bulk_marks_only_active_class_roster_and_is_idempotent(self):
        offline_student = Student.objects.create(
            department=self.department,
            registration_number="TRV-2026-0002",
            first_name="Offline",
            last_name="Learner",
            admission_year=2026,
        )
        Enrollment.objects.create(
            student=offline_student,
            course=self.course,
            class_group=self.group,
            status=Enrollment.Status.ACTIVE,
        )
        inactive_student = Student.objects.create(
            department=self.department,
            registration_number="TRV-2026-0003",
            first_name="Inactive",
            last_name="Learner",
            admission_year=2026,
        )
        Enrollment.objects.create(
            student=inactive_student,
            course=self.course,
            class_group=self.group,
            status=Enrollment.Status.APPROVED,
        )
        outside_student = Student.objects.create(
            department=self.department,
            registration_number="TRV-2026-0004",
            first_name="Outside",
            last_name="Learner",
            admission_year=2026,
        )

        self.client.force_authenticate(self.teacher)
        opened = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.group.id), "title": "Morning class"},
            format="json",
        )
        self.assertEqual(opened.status_code, 201, opened.content)
        session_id = opened.json()["id"]

        roster = self.client.get(f"/api/v1/attendance/sessions/{session_id}/roster/")
        self.assertEqual(roster.status_code, 200, roster.content)
        self.assertEqual(roster.json()["count"], 2)
        self.assertEqual(
            {row["student"] for row in roster.json()["results"]},
            {str(self.student.id), str(offline_student.id)},
        )
        self.assertTrue(all(row["status"] is None for row in roster.json()["results"]))

        marks = {
            "records": [
                {
                    "student": str(self.student.id),
                    "status": AttendanceRecord.Status.PRESENT,
                },
                {
                    "student": str(offline_student.id),
                    "status": AttendanceRecord.Status.EXCUSED,
                },
            ]
        }
        response = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/mark/",
            marks,
            format="json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(len(response.json()["records"]), 2)
        self.assertEqual(
            AttendanceRecord.objects.filter(session_id=session_id).count(), 2
        )
        self.assertEqual(
            AuditLog.objects.filter(action="attendance_record_marked").count(), 2
        )

        repeated = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/mark/",
            marks,
            format="json",
        )
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(
            AttendanceRecord.objects.filter(session_id=session_id).count(), 2
        )
        self.assertEqual(
            AuditLog.objects.filter(action="attendance_record_marked").count(), 2
        )

        invalid_roster = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/mark/",
            {
                "records": [
                    {"student": str(outside_student.id), "status": "PRESENT"},
                ]
            },
            format="json",
        )
        self.assertEqual(invalid_roster.status_code, 400, invalid_roster.content)
        self.assertEqual(
            AttendanceRecord.objects.filter(session_id=session_id).count(), 2
        )

        self.client.force_authenticate(self.student_user)
        forbidden_roster = self.client.get(
            f"/api/v1/attendance/sessions/{session_id}/roster/"
        )
        self.assertEqual(forbidden_roster.status_code, 403, forbidden_roster.content)
        forbidden_mark = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/mark/",
            marks,
            format="json",
        )
        self.assertEqual(forbidden_mark.status_code, 403, forbidden_mark.content)

    def test_scoped_hod_can_bulk_mark_attendance_in_their_department(self):
        hod = create_role_user(
            "attendance-hod",
            role=Role.HOD,
            unit=self.course.unit,
        )
        RoleScope.objects.create(user=hod, department=self.department)
        session = AttendanceSession.objects.create(
            class_group=self.group,
            opened_by=self.teacher,
            title="HOD review",
        )

        self.client.force_authenticate(hod)
        response = self.client.post(
            f"/api/v1/attendance/sessions/{session.id}/mark/",
            {
                "records": [
                    {
                        "student": str(self.student.id),
                        "status": AttendanceRecord.Status.LATE,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(
            AttendanceRecord.objects.get(session=session, student=self.student).status,
            AttendanceRecord.Status.LATE,
        )

    def test_class_cannot_have_two_open_attendance_sessions(self):
        self.client.force_authenticate(self.teacher)
        first = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.group.id), "title": "Lecture"},
            format="json",
        )
        self.assertEqual(first.status_code, 201, first.content)
        duplicate = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.group.id), "title": "Second session"},
            format="json",
        )
        self.assertEqual(duplicate.status_code, 409, duplicate.content)
        self.assertEqual(
            AttendanceSession.objects.filter(
                class_group=self.group, is_open=True
            ).count(),
            1,
        )

    def test_expired_qr_token_is_rejected(self):
        session = AttendanceSession.objects.create(
            class_group=self.group, opened_by=self.teacher
        )
        raw_token = "expired-qr-code"
        QrToken.objects.create(
            session=session,
            token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/attendance/check-in/", {"token": raw_token}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AttendanceRecord.objects.filter(session=session).exists())

    def test_active_class_roster_can_check_in_without_course_access(self):
        session = AttendanceSession.objects.create(
            class_group=self.group, opened_by=self.teacher
        )
        raw_token = "roster-without-course-access"
        QrToken.objects.create(
            session=session,
            token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        CourseAccess.objects.filter(student=self.student, course=self.course).update(
            is_active=False
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/attendance/check-in/", {"token": raw_token}, format="json"
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(
            AttendanceRecord.objects.filter(
                session=session, student=self.student
            ).exists()
        )

    def test_course_access_does_not_allow_check_in_outside_session_roster(self):
        other_group = ClassGroup.objects.create(
            course=self.course,
            academic_period=self.period,
            name="Group B",
            code="TRV-101-B",
            status=ClassGroup.Status.RUNNING,
        )
        Enrollment.objects.filter(student=self.student, course=self.course).update(
            class_group=other_group
        )
        session = AttendanceSession.objects.create(
            class_group=self.group, opened_by=self.teacher
        )
        raw_token = "course-access-outside-roster"
        QrToken.objects.create(
            session=session,
            token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/attendance/check-in/", {"token": raw_token}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AttendanceRecord.objects.filter(session=session).exists())

    def test_course_access_does_not_allow_check_in_without_active_enrollment(self):
        Enrollment.objects.filter(student=self.student, course=self.course).update(
            status=Enrollment.Status.APPROVED
        )
        session = AttendanceSession.objects.create(
            class_group=self.group, opened_by=self.teacher
        )
        raw_token = "course-access-without-active-enrollment"
        QrToken.objects.create(
            session=session,
            token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        self.client.force_authenticate(self.student_user)
        response = self.client.post(
            "/api/v1/attendance/check-in/", {"token": raw_token}, format="json"
        )
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AttendanceRecord.objects.filter(session=session).exists())


class SchedulingAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
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
        self.period = AcademicPeriod.objects.create(
            name="Authorization Term",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
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
        self.admin = User.objects.create_user("schedule-admin", role=Role.ADMIN)
        self.teacher_manager = User.objects.create_user("schedule-teacher-manager")
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.TEACHER, unit=self.wti
        )
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.UNIT_MANAGER, unit=self.wta
        )
        self.teacher_manager.clear_role_cache()
        self.wta_teacher = User.objects.create_user(
            "schedule-wta-teacher", role=Role.TEACHER, unit=self.wta
        )
        self.wti_other_teacher = User.objects.create_user(
            "schedule-wti-other", role=Role.TEACHER, unit=self.wti
        )
        self.wds_teacher = User.objects.create_user(
            "schedule-wds-teacher", role=Role.TEACHER, unit=self.wds
        )
        self.hod = User.objects.create_user(
            "schedule-hod", role=Role.HOD, unit=self.wti
        )
        RoleScope.objects.create(user=self.hod, department=self.wti_department)

        self.wti_course = self._course(self.wti_department, "WTI-101")
        self.wti_other_course = self._course(self.wti_other_department, "WTI-201")
        self.wta_course = self._course(self.wta_department, "WTA-101")
        self.wds_course = self._course(self.wds_department, "WDS-101")
        CourseAssignment.objects.create(
            unit=self.wti,
            course=self.wti_course,
            teacher=self.teacher_manager,
            can_edit_content=True,
        )

        self.wti_group = self._class_group(
            self.wti_course, self.teacher_manager, "WTI-G1"
        )
        self.wti_other_group = self._class_group(
            self.wti_other_course, self.wti_other_teacher, "WTI-G2"
        )
        self.wta_group = self._class_group(self.wta_course, self.wta_teacher, "WTA-G1")
        self.wds_group = self._class_group(self.wds_course, self.wds_teacher, "WDS-G1")
        self.wti_assignment = ClassTeacher.objects.create(
            class_group=self.wti_group,
            teacher=self.teacher_manager,
            role=ClassTeacher.Role.LEAD,
        )
        self.wti_other_assignment = ClassTeacher.objects.create(
            class_group=self.wti_other_group,
            teacher=self.wti_other_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        self.wta_assignment = ClassTeacher.objects.create(
            class_group=self.wta_group,
            teacher=self.wta_teacher,
            role=ClassTeacher.Role.LEAD,
        )
        self.wds_assignment = ClassTeacher.objects.create(
            class_group=self.wds_group,
            teacher=self.wds_teacher,
            role=ClassTeacher.Role.LEAD,
        )

        self.wti_room = Room.objects.create(
            department=self.wti_department, name="Institute Room", code="AUTH-WTI"
        )
        self.wti_other_room = Room.objects.create(
            department=self.wti_other_department,
            name="Other Institute Room",
            code="AUTH-WTI2",
        )
        self.wta_room = Room.objects.create(
            department=self.wta_department, name="Travel Room", code="AUTH-WTA"
        )
        self.wds_room = Room.objects.create(
            department=self.wds_department, name="Driving Room", code="AUTH-WDS"
        )
        self.wti_slot = self._slot(self.wti_group, self.wti_room, 0)
        self.wti_other_slot = self._slot(self.wti_other_group, self.wti_other_room, 1)
        self.wta_slot = self._slot(self.wta_group, self.wta_room, 2)
        self.wds_slot = self._slot(self.wds_group, self.wds_room, 3)

        self.student_user = User.objects.create_user("schedule-student")
        student = Student.objects.create(
            user=self.student_user,
            department=self.wti_department,
            registration_number="WTI/INS/2026/0001",
            first_name="Schedule",
            last_name="Student",
            email="schedule-student@example.test",
            admission_year=2026,
        )
        enrollment = Enrollment.objects.create(student=student, course=self.wti_course)
        CourseAccess.objects.create(
            student=student, course=self.wti_course, enrollment=enrollment
        )

    def _course(self, department, code):
        return Course.objects.create(
            department=department,
            created_by=self.admin,
            title=f"Course {code}",
            code=code,
            status=Course.Status.PUBLISHED,
        )

    def _class_group(self, course, teacher, code):
        return ClassGroup.objects.create(
            course=course,
            academic_period=self.period,
            name=code,
            code=code,
        )

    @staticmethod
    def _slot(class_group, room, weekday):
        return TimetableSlot.objects.create(
            class_group=class_group,
            room=room,
            weekday=weekday,
            starts_at=time(9),
            ends_at=time(10),
            effective_from=date(2026, 1, 1),
        )

    @staticmethod
    def _ids(queryset):
        return set(queryset.values_list("pk", flat=True))

    def test_teacher_and_unit_manager_scopes_union_without_cross_unit_leaks(self):
        self.assertSetEqual(
            self._ids(ClassGroup.objects.for_user(self.teacher_manager)),
            {self.wti_group.pk, self.wta_group.pk},
        )
        self.assertSetEqual(
            self._ids(ClassTeacher.objects.for_user(self.teacher_manager)),
            {self.wti_assignment.pk, self.wta_assignment.pk},
        )
        self.assertSetEqual(
            self._ids(TimetableSlot.objects.for_user(self.teacher_manager)),
            {self.wti_slot.pk, self.wta_slot.pk},
        )
        self.assertSetEqual(
            self._ids(Room.objects.for_user(self.teacher_manager)),
            {self.wti_room.pk, self.wti_other_room.pk, self.wta_room.pk},
        )

    def test_class_transitions_follow_teacher_and_manager_scope(self):
        self.client.force_authenticate(self.teacher_manager)
        for group in (self.wti_group, self.wta_group):
            response = self.client.post(
                f"/api/v1/class-groups/{group.pk}/transition/",
                {"status": ClassGroup.Status.OPEN},
                format="json",
            )
            self.assertEqual(response.status_code, 200, response.content)

        response = self.client.post(
            f"/api/v1/class-groups/{self.wds_group.pk}/transition/",
            {"status": ClassGroup.Status.OPEN},
            format="json",
        )
        self.assertEqual(response.status_code, 404, response.content)

    def test_hod_scope_is_limited_to_assigned_departments(self):
        self.assertSetEqual(
            self._ids(ClassGroup.objects.for_user(self.hod)), {self.wti_group.pk}
        )
        self.assertSetEqual(
            self._ids(ClassTeacher.objects.for_user(self.hod)),
            {self.wti_assignment.pk},
        )
        self.assertSetEqual(
            self._ids(TimetableSlot.objects.for_user(self.hod)), {self.wti_slot.pk}
        )
        self.assertSetEqual(
            self._ids(Room.objects.for_user(self.hod)), {self.wti_room.pk}
        )

    def test_student_without_unit_assignment_sees_only_accessible_schedule(self):
        self.assertSetEqual(
            self._ids(ClassGroup.objects.for_user(self.student_user)),
            {self.wti_group.pk},
        )
        self.assertSetEqual(
            self._ids(TimetableSlot.objects.for_user(self.student_user)),
            {self.wti_slot.pk},
        )
        self.assertSetEqual(
            self._ids(Room.objects.for_user(self.student_user)), {self.wti_room.pk}
        )

    def test_directors_and_auditors_are_global_read_only(self):
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = User.objects.create_user(f"schedule-read-only-{role}", role=role)
            self.assertSetEqual(
                self._ids(ClassGroup.objects.for_user(user)),
                {
                    self.wti_group.pk,
                    self.wti_other_group.pk,
                    self.wta_group.pk,
                    self.wds_group.pk,
                },
            )
            self.assertSetEqual(
                self._ids(TimetableSlot.objects.for_user(user)),
                {
                    self.wti_slot.pk,
                    self.wti_other_slot.pk,
                    self.wta_slot.pk,
                    self.wds_slot.pk,
                },
            )
            permission = SchedulingPermission()
            self.assertTrue(
                permission.has_permission(
                    SimpleNamespace(user=user, method="GET"),
                    SimpleNamespace(),
                )
            )
            self.assertFalse(
                permission.has_permission(
                    SimpleNamespace(user=user, method="POST"),
                    SimpleNamespace(assignment_management=True),
                )
            )

    def test_teacher_manager_writes_respect_each_assignment_scope(self):
        self.client.force_authenticate(self.teacher_manager)
        response = self.client.post(
            "/api/v1/class-groups/",
            {
                "course": str(self.wti_course.pk),
                "lead_teacher": str(self.teacher_manager.pk),
                "academic_period": str(self.period.pk),
                "name": "WTI teacher managed",
                "code": "WTI-G3",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        response = self.client.post(
            "/api/v1/class-groups/",
            {
                "course": str(self.wta_course.pk),
                "lead_teacher": str(self.wta_teacher.pk),
                "academic_period": str(self.period.pk),
                "name": "WTA manager managed",
                "code": "WTA-G2",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        response = self.client.post(
            "/api/v1/rooms/",
            {
                "department": str(self.wti_department.pk),
                "name": "Out of scope",
                "code": "AUTH-OUT",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)

        response = self.client.post(
            "/api/v1/rooms/",
            {
                "department": str(self.wta_department.pk),
                "name": "Managed room",
                "code": "AUTH-MANAGED",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        assistant = User.objects.create_user(
            "schedule-wta-assistant", role=Role.TEACHER, unit=self.wta
        )
        response = self.client.post(
            "/api/v1/class-teachers/",
            {
                "class_group": str(self.wta_group.pk),
                "teacher": str(assistant.pk),
                "role": ClassTeacher.Role.ASSISTANT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)

        response = self.client.post(
            "/api/v1/class-teachers/",
            {
                "class_group": str(self.wti_group.pk),
                "teacher": str(self.wti_other_teacher.pk),
                "role": ClassTeacher.Role.ASSISTANT,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400, response.content)


class AttendanceAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Attendance authorization", code="ATT-AUTH")
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
        self.admin = User.objects.create_user("attendance-admin", role=Role.ADMIN)
        self.teacher_manager = User.objects.create_user("attendance-teacher-manager")
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.TEACHER, unit=self.wti
        )
        RoleAssignment.objects.create(
            user=self.teacher_manager, role=Role.UNIT_MANAGER, unit=self.wta
        )
        self.teacher_manager.clear_role_cache()
        self.wti_other_teacher = User.objects.create_user(
            "attendance-wti-other", role=Role.TEACHER, unit=self.wti
        )
        self.wta_teacher = User.objects.create_user(
            "attendance-wta-teacher", role=Role.TEACHER, unit=self.wta
        )
        self.wds_teacher = User.objects.create_user(
            "attendance-wds-teacher", role=Role.TEACHER, unit=self.wds
        )
        self.hod = User.objects.create_user(
            "attendance-hod", role=Role.HOD, unit=self.wti
        )
        RoleScope.objects.create(user=self.hod, department=self.wti_department)

        self.wti_course = self._course(self.wti_department, "ATT-WTI")
        self.wti_other_course = self._course(self.wti_other_department, "ATT-WTI2")
        self.wta_course = self._course(self.wta_department, "ATT-WTA")
        self.wds_course = self._course(self.wds_department, "ATT-WDS")
        self.wti_group = self._class_group(
            self.wti_course, self.teacher_manager, "ATT-WTI-G1"
        )
        self.wti_other_group = self._class_group(
            self.wti_other_course, self.wti_other_teacher, "ATT-WTI-G2"
        )
        self.wta_group = self._class_group(
            self.wta_course, self.wta_teacher, "ATT-WTA-G1"
        )
        self.wds_group = self._class_group(
            self.wds_course, self.wds_teacher, "ATT-WDS-G1"
        )
        self.wti_session = self._session(self.wti_group, "WTI session", is_open=True)
        self.wti_other_session = self._session(
            self.wti_other_group, "Other WTI session", is_open=False
        )
        self.wta_session = self._session(self.wta_group, "WTA session", is_open=False)
        self.wds_session = self._session(self.wds_group, "WDS session", is_open=False)

        self.student_user = User.objects.create_user("attendance-student")
        self.student = self._student(
            self.wti_department,
            "WTI/INS/2026/0001",
            "attendance-student@example.test",
            user=self.student_user,
        )
        self.wti_other_student = self._student(
            self.wti_other_department,
            "WTI/OIN/2026/0001",
            "attendance-wti-other@example.test",
        )
        self.wta_student = self._student(
            self.wta_department,
            "WTA/TRV/2026/0001",
            "attendance-wta@example.test",
        )
        self.wds_student = self._student(
            self.wds_department,
            "WDS/DRV/2026/0001",
            "attendance-wds@example.test",
        )
        enrollment = Enrollment.objects.create(
            student=self.student, course=self.wti_course
        )
        CourseAccess.objects.create(
            student=self.student, course=self.wti_course, enrollment=enrollment
        )
        self.wti_record = AttendanceRecord.objects.create(
            session=self.wti_session, student=self.student
        )
        self.wti_other_record = AttendanceRecord.objects.create(
            session=self.wti_other_session, student=self.wti_other_student
        )
        self.wta_record = AttendanceRecord.objects.create(
            session=self.wta_session, student=self.wta_student
        )
        self.wds_record = AttendanceRecord.objects.create(
            session=self.wds_session, student=self.wds_student
        )

    def _course(self, department, code):
        return Course.objects.create(
            department=department,
            created_by=self.admin,
            title=f"Course {code}",
            code=code,
        )

    @staticmethod
    def _class_group(course, teacher, code):
        class_group = ClassGroup.objects.create(
            course=course,
            name=code,
            code=code,
            status=ClassGroup.Status.RUNNING,
        )
        ClassTeacher.objects.create(
            class_group=class_group,
            teacher=teacher,
            role=ClassTeacher.Role.LEAD,
        )
        return class_group

    def _session(self, class_group, title, *, is_open):
        return AttendanceSession.objects.create(
            class_group=class_group,
            opened_by=self.admin,
            title=title,
            is_open=is_open,
        )

    @staticmethod
    def _student(department, registration_number, email, user=None):
        return Student.objects.create(
            user=user,
            department=department,
            registration_number=registration_number,
            first_name="Attendance",
            last_name="Student",
            email=email,
            admission_year=2026,
        )

    @staticmethod
    def _ids(queryset):
        return set(queryset.values_list("pk", flat=True))

    def test_teacher_and_unit_manager_scopes_union_for_sessions_and_records(self):
        self.assertSetEqual(
            self._ids(AttendanceSession.objects.for_user(self.teacher_manager)),
            {self.wti_session.pk, self.wta_session.pk},
        )
        self.assertSetEqual(
            self._ids(AttendanceRecord.objects.for_user(self.teacher_manager)),
            {self.wti_record.pk, self.wta_record.pk},
        )
        permission = AttendancePermission()
        request = SimpleNamespace(user=self.teacher_manager, method="POST")
        view = SimpleNamespace(action="close")
        self.assertTrue(permission.has_permission(request, view))
        self.assertTrue(
            permission.has_object_permission(request, view, self.wta_session)
        )
        self.assertFalse(
            permission.has_object_permission(request, view, self.wti_other_session)
        )

    def test_hod_scope_is_limited_to_assigned_department(self):
        self.assertSetEqual(
            self._ids(AttendanceSession.objects.for_user(self.hod)),
            {self.wti_session.pk},
        )
        self.assertSetEqual(
            self._ids(AttendanceRecord.objects.for_user(self.hod)),
            {self.wti_record.pk},
        )

    def test_student_sees_only_own_records_and_open_accessible_sessions(self):
        self.assertSetEqual(
            self._ids(AttendanceSession.objects.for_user(self.student_user)),
            {self.wti_session.pk},
        )
        self.assertSetEqual(
            self._ids(AttendanceRecord.objects.for_user(self.student_user)),
            {self.wti_record.pk},
        )

    def test_directors_and_auditors_are_global_read_only(self):
        all_session_ids = {
            self.wti_session.pk,
            self.wti_other_session.pk,
            self.wta_session.pk,
            self.wds_session.pk,
        }
        all_record_ids = {
            self.wti_record.pk,
            self.wti_other_record.pk,
            self.wta_record.pk,
            self.wds_record.pk,
        }
        permission = AttendancePermission()
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = User.objects.create_user(f"attendance-read-only-{role}", role=role)
            self.assertSetEqual(
                self._ids(AttendanceSession.objects.for_user(user)), all_session_ids
            )
            self.assertSetEqual(
                self._ids(AttendanceRecord.objects.for_user(user)), all_record_ids
            )
            self.assertTrue(
                permission.has_permission(
                    SimpleNamespace(user=user, method="GET"),
                    SimpleNamespace(action="list"),
                )
            )
            self.assertFalse(
                permission.has_permission(
                    SimpleNamespace(user=user, method="POST"),
                    SimpleNamespace(action="open"),
                )
            )

    def test_unit_manager_can_open_qr_and_close_only_in_assigned_unit(self):
        self.client.force_authenticate(self.teacher_manager)
        response = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.wta_group.pk), "title": "WTA attendance"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        session_id = response.json()["id"]

        response = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/qr/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("token", response.json())

        response = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/close/", {}, format="json"
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertFalse(AttendanceSession.objects.get(pk=session_id).is_open)

        response = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": str(self.wti_other_group.pk), "title": "Wrong unit"},
            format="json",
        )
        self.assertEqual(response.status_code, 403, response.content)
