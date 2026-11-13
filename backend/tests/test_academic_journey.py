from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.academics.models import Course
from apps.accounts.models import RoleScope, User
from apps.accounts.roles import Role
from apps.assessment.models import AssessmentTemplate, Grade
from apps.attendance.models import AttendanceRecord
from apps.enrollment.models import CourseAccess, Enrollment
from apps.finance.models import (
    Account,
    AccountingPeriod,
    CashAccount,
    FeeStructure,
    Payment,
)
from apps.org.models import AcademicPeriod, BusinessUnit, Campus, Department
from apps.people.models import Student
from apps.scheduling.models import ClassGroup, ClassTeacher, TimetableSlot
from tests.helpers import create_role_user


class AcademicJourneyTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.campus = Campus.objects.create(name="Journey Campus", code="JOURNEY")
        self.unit = BusinessUnit.objects.create(
            code="JRN",
            name="Journey Institute",
            kind=BusinessUnit.Kind.ACADEMIC,
        )
        self.department = Department.objects.create(
            unit=self.unit,
            campus=self.campus,
            name="Journey Studies",
            code="JRN",
        )
        self.period = AcademicPeriod.objects.create(
            name="Journey Term",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            kind=AcademicPeriod.Kind.TERM,
            unit=self.unit,
        )
        self.admin = User.objects.create_user("journey-admin", role=Role.ADMIN)
        self.teacher = create_role_user(
            "journey-teacher", role=Role.TEACHER, unit=self.unit
        )
        self.unit_manager = create_role_user(
            "journey-manager", role=Role.UNIT_MANAGER, unit=self.unit
        )
        self.bursar = create_role_user(
            "journey-bursar", role=Role.BURSAR, unit=self.unit
        )
        self.hod = create_role_user("journey-hod", role=Role.HOD, unit=self.unit)
        RoleScope.objects.create(user=self.hod, department=self.department)
        receivable_account = self.create_account(
            "1100", "Student receivables", Account.Type.ASSET
        )
        cash_account_record = self.create_account(
            "1010", "M-Pesa agent float", Account.Type.ASSET
        )
        income_account = self.create_account(
            "4000", "Student fee income", Account.Type.INCOME
        )
        discount_account = self.create_account(
            "4900", "Fee discounts", Account.Type.EXPENSE
        )
        refund_account = self.create_account("4100", "Fee refunds", Account.Type.INCOME)
        self.cash_account = CashAccount.objects.create(
            account=cash_account_record,
            kind=CashAccount.Kind.MPESA_AGENT,
            name="Agent float",
            custody_unit=self.unit,
            custodian=self.bursar,
        )
        self.fee_structure = FeeStructure.objects.create(
            unit=self.unit,
            code="TUITION",
            name="Tuition",
            amount=Decimal("1000.00"),
            receivable_account=receivable_account,
            income_account=income_account,
            discount_account=discount_account,
            refund_account=refund_account,
        )
        AccountingPeriod.objects.create(start=date(2026, 1, 1), end=date(2026, 12, 31))

    @staticmethod
    def create_account(code, name, account_type):
        return Account.objects.create(code=code, name=name, type=account_type)

    @patch("apps.finance.views.get_storage_client")
    def test_course_to_attendance_to_published_grade_journey(self, get_storage_client):
        storage = get_storage_client.return_value
        storage.get_object.side_effect = lambda **kwargs: {
            "Body": BytesIO(storage.put_object.call_args.kwargs["Body"])
        }
        self.client.force_authenticate(self.admin)
        course_response = self.client.post(
            "/api/v1/courses/",
            {
                "department": str(self.department.id),
                "title": "Journey Operations",
                "code": "JRN-101",
            },
            format="json",
        )
        self.assertEqual(course_response.status_code, 201, course_response.content)
        course = course_response.json()

        published_course = self.client.post(
            f"/api/v1/courses/{course['slug']}/publish/",
            {"version": course["version"]},
            format="json",
        )
        self.assertEqual(published_course.status_code, 200, published_course.content)
        self.assertEqual(published_course.json()["status"], Course.Status.PUBLISHED)

        class_response = self.client.post(
            "/api/v1/class-groups/",
            {
                "course": course["id"],
                "lead_teacher": str(self.teacher.id),
                "academic_period": str(self.period.id),
                "name": "Journey Cohort",
                "code": "JRN-101-A",
                "capacity": 20,
            },
            format="json",
        )
        self.assertEqual(class_response.status_code, 201, class_response.content)
        class_group_id = class_response.json()["id"]
        self.assertEqual(class_response.json()["lead_teacher_id"], str(self.teacher.id))
        self.assertTrue(
            ClassTeacher.objects.filter(
                class_group_id=class_group_id,
                teacher=self.teacher,
                role=ClassTeacher.Role.LEAD,
                is_active=True,
            ).exists()
        )

        room_response = self.client.post(
            "/api/v1/rooms/",
            {
                "department": str(self.department.id),
                "name": "Journey Room",
                "code": "JRN-R1",
                "capacity": 24,
            },
            format="json",
        )
        self.assertEqual(room_response.status_code, 201, room_response.content)
        timetable_response = self.client.post(
            "/api/v1/timetable/",
            {
                "class_group": class_group_id,
                "room": room_response.json()["id"],
                "weekday": 0,
                "starts_at": "09:00:00",
                "ends_at": "10:00:00",
                "effective_from": date.today().isoformat(),
            },
            format="json",
        )
        self.assertEqual(
            timetable_response.status_code, 201, timetable_response.content
        )
        self.assertTrue(
            TimetableSlot.objects.filter(class_group_id=class_group_id).exists()
        )

        open_class = self.client.post(
            f"/api/v1/class-groups/{class_group_id}/transition/",
            {"status": ClassGroup.Status.OPEN},
            format="json",
        )
        self.assertEqual(open_class.status_code, 200, open_class.content)

        self.client.force_authenticate(self.unit_manager)
        registration_response = self.client.post(
            "/api/v1/students/",
            {
                "unit": str(self.unit.id),
                "class_group": class_group_id,
                "first_name": "Amina",
                "last_name": "Njeri",
                "phone": "+254700000000",
            },
            format="json",
        )
        self.assertEqual(
            registration_response.status_code, 201, registration_response.content
        )
        student_id = registration_response.json()["id"]
        enrollment_id = registration_response.json()["enrollment_id"]
        student = Student.objects.get(pk=student_id)
        self.assertIsNone(student.user_id)
        self.assertEqual(student.home_unit, self.unit)
        self.assertEqual(
            Enrollment.objects.get(pk=enrollment_id).status, Enrollment.Status.ACTIVE
        )
        self.assertTrue(
            CourseAccess.objects.filter(
                student_id=student_id, course_id=course["id"], is_active=True
            ).exists()
        )

        running_class = self.client.post(
            f"/api/v1/class-groups/{class_group_id}/transition/",
            {"status": ClassGroup.Status.RUNNING},
            format="json",
        )
        self.assertEqual(running_class.status_code, 200, running_class.content)

        self.client.force_authenticate(self.teacher)
        session_response = self.client.post(
            "/api/v1/attendance/sessions/open/",
            {"class_group": class_group_id, "title": "Journey attendance"},
            format="json",
        )
        self.assertEqual(session_response.status_code, 201, session_response.content)
        session_id = session_response.json()["id"]
        marked = self.client.post(
            f"/api/v1/attendance/sessions/{session_id}/mark/",
            {
                "records": [
                    {
                        "student": student_id,
                        "status": AttendanceRecord.Status.PRESENT,
                    }
                ]
            },
            format="json",
        )
        self.assertEqual(marked.status_code, 200, marked.content)
        self.assertEqual(len(marked.json()["records"]), 1)
        self.assertEqual(
            marked.json()["records"][0]["status"], AttendanceRecord.Status.PRESENT
        )

        self.client.force_authenticate(self.admin)
        template_response = self.client.post(
            "/api/v1/assessment-templates/",
            {
                "course": course["id"],
                "title": "Journey Assessment",
                "instructions": "Complete the practical exercise.",
                "kind": AssessmentTemplate.Kind.ASSIGNMENT,
                "maximum_score": "100.00",
            },
            format="json",
        )
        self.assertEqual(template_response.status_code, 201, template_response.content)
        assessment_response = self.client.post(
            "/api/v1/assessments/",
            {
                "template": template_response.json()["id"],
                "class_group": class_group_id,
                "weight": "1.00",
            },
            format="json",
        )
        self.assertEqual(
            assessment_response.status_code, 201, assessment_response.content
        )
        assessment_id = assessment_response.json()["id"]
        published_assessment = self.client.post(
            f"/api/v1/assessments/{assessment_id}/publish/", {}, format="json"
        )
        self.assertEqual(
            published_assessment.status_code, 200, published_assessment.content
        )

        self.client.force_authenticate(self.teacher)
        grade_response = self.client.post(
            "/api/v1/grades/",
            {
                "assessment": assessment_id,
                "enrollment": enrollment_id,
                "score": "88.00",
                "feedback": "Strong practical work.",
                "change_note": "Recorded from the marked practical exercise.",
            },
            format="json",
        )
        self.assertEqual(grade_response.status_code, 201, grade_response.content)
        grade_id = grade_response.json()["id"]
        submitted_grade = self.client.post(
            f"/api/v1/grades/{grade_id}/submit-for-approval/", {}, format="json"
        )
        self.assertEqual(submitted_grade.status_code, 200, submitted_grade.content)

        self.client.force_authenticate(self.hod)
        approved_grade = self.client.post(
            f"/api/v1/grades/{grade_id}/approve/", {}, format="json"
        )
        self.assertEqual(approved_grade.status_code, 200, approved_grade.content)
        self.assertEqual(approved_grade.json()["status"], Grade.Status.APPROVED)
        published_grade = self.client.post(
            f"/api/v1/grades/{grade_id}/publish/", {}, format="json"
        )
        self.assertEqual(published_grade.status_code, 200, published_grade.content)
        self.assertEqual(published_grade.json()["status"], Grade.Status.PUBLISHED)
        self.assertEqual(published_grade.json()["official_score"], "88.00")

        self.client.force_authenticate(self.bursar)
        invoice_response = self.client.post(
            "/api/v1/invoices/",
            {
                "student": student_id,
                "fee_structure": str(self.fee_structure.pk),
                "issue_date": "2026-11-01",
                "due_date": "2026-11-30",
                "idempotency_key": "journey-invoice",
            },
            format="json",
        )
        self.assertEqual(invoice_response.status_code, 201, invoice_response.content)
        payment_response = self.client.post(
            "/api/v1/payments/",
            {
                "invoice": invoice_response.json()["id"],
                "cash_account": str(self.cash_account.pk),
                "amount": "500.00",
                "channel": Payment.Channel.MPESA_AGENT,
                "received_at": timezone.now().isoformat(),
                "idempotency_key": "journey-payment",
                "mpesa_code": "JOURNEY123",
            },
            format="json",
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        receipt = payment_response.json()["receipt"]
        self.assertTrue(receipt["number"])

        statement_response = self.client.get(
            f"/api/v1/students/{student_id}/statement/"
        )
        self.assertEqual(
            statement_response.status_code, 200, statement_response.content
        )
        self.assertEqual(statement_response.json()["balance"], "500.00")
        self.assertEqual(len(statement_response.json()["lines"]), 2)

        receipt_response = self.client.get(f"/api/v1/receipts/{receipt['id']}/pdf/")
        self.assertEqual(receipt_response.status_code, 200, receipt_response.content)
        self.assertEqual(receipt_response["Content-Type"], "application/pdf")
        self.assertTrue(receipt_response.content.startswith(b"%PDF"))

        self.client.force_authenticate(self.hod)
        transcript_response = self.client.get(f"/api/v1/transcripts/{student_id}/")
        self.assertEqual(
            transcript_response.status_code, 200, transcript_response.content
        )
        self.assertEqual(transcript_response["Content-Type"], "application/pdf")
        self.assertTrue(transcript_response.content.startswith(b"%PDF"))
        self.assertIsNone(Student.objects.get(pk=student_id).user_id)
