import hashlib
from datetime import date, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.attendance.models import AttendanceRecord, AttendanceSession, QrToken
from apps.enrollment.models import CourseAccess, Enrollment
from apps.org.models import Campus, Department
from apps.people.models import Student
from apps.scheduling.models import ClassGroup, Room, TimetableSlot
from tests.helpers import create_role_user


class SchedulingAttendanceTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        campus = Campus.objects.create(name="Main", code="MAIN")
        self.department = Department.objects.create(
            campus=campus, name="Travel", code="TRV"
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
        enrollment = Enrollment.objects.create(
            student=self.student,
            course=self.course,
            status=Enrollment.Status.ACTIVE,
        )
        CourseAccess.objects.create(
            student=self.student, course=self.course, enrollment=enrollment
        )
        self.group = ClassGroup.objects.create(
            course=self.course,
            teacher=self.teacher,
            name="Group A",
            code="TRV-101-A",
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
            teacher=self.teacher,
            name="Group B",
            code="TRV-101-B",
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

    def test_timetable_rejects_overlapping_room_booking(self):
        room = Room.objects.create(
            department=self.department, name="Room 1", code="R1", capacity=30
        )
        first_teacher = create_role_user("teacher-1", role=Role.TEACHER)
        second_teacher = create_role_user("teacher-2", role=Role.TEACHER)
        first_group = ClassGroup.objects.create(
            course=self.course,
            teacher=first_teacher,
            name="Group A",
            code="TRV-101-R1",
        )
        second_group = ClassGroup.objects.create(
            course=self.course,
            teacher=second_teacher,
            name="Group B",
            code="TRV-101-R2",
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
        ClassGroup.objects.create(
            course=self.course,
            teacher=other_teacher,
            name="Group B",
            code="TRV-101-B",
        )
        self.client.force_authenticate(self.teacher)
        response = self.client.get("/api/v1/class-groups/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [row["id"] for row in response.json()["results"]], [str(self.group.id)]
        )

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

    def test_student_without_active_course_access_cannot_check_in(self):
        session = AttendanceSession.objects.create(
            class_group=self.group, opened_by=self.teacher
        )
        raw_token = "no-access-qr-code"
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
        self.assertEqual(response.status_code, 400, response.content)
        self.assertFalse(AttendanceRecord.objects.filter(session=session).exists())
