from io import BytesIO
from xml.sax.saxutils import escape

from django.db.models import OuterRef, Subquery
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.accounts.roles import ADMIN_ROLES, Role
from apps.assessment.models import Grade, Submission
from apps.people.models import Student


class StudentTranscriptView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request, student_id=None):
        students = Student.objects.select_related("department", "user")
        if student_id is None and request.user.role == Role.STUDENT:
            student = get_object_or_404(students, user=request.user, is_active=True)
        elif student_id is None:
            raise PermissionDenied(
                "A student id is required for staff transcript access."
            )
        else:
            student = get_object_or_404(students, pk=student_id)
        if request.user.role == Role.STUDENT:
            allowed = student.user_id == request.user.id
        elif request.user.role in ADMIN_ROLES | {Role.DIRECTOR}:
            allowed = True
        elif request.user.role == Role.HOD:
            allowed = student.department.role_scopes.filter(user=request.user).exists()
        else:
            allowed = False
        if not allowed:
            raise PermissionDenied("You may not view this student's transcript.")

        latest_submission = (
            Submission.objects.filter(
                assessment_id=OuterRef("submission__assessment_id"),
                student_id=OuterRef("submission__student_id"),
            )
            .order_by("-attempt_number")
            .values("id")[:1]
        )
        grades = (
            Grade.objects.filter(
                submission__student=student,
                status=Grade.Status.PUBLISHED,
                submission_id=Subquery(latest_submission),
            )
            .select_related("submission__assessment__course")
            .order_by(
                "submission__assessment__course__title", "submission__assessment__title"
            )
        )
        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            rightMargin=36,
            leftMargin=36,
            topMargin=36,
            bottomMargin=36,
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph("Watan LMS — Academic Transcript", styles["Title"]),
            Spacer(1, 12),
            Paragraph(
                f"<b>Student:</b> {escape(student.first_name)} {escape(student.last_name)}"
                f" &nbsp;&nbsp; <b>Registration:</b> {escape(student.registration_number)}"
                f" &nbsp;&nbsp; <b>Department:</b> {escape(student.department.name)}",
                styles["BodyText"],
            ),
            Spacer(1, 16),
        ]
        rows = [["Course", "Assessment", "Score", "Maximum", "Published"]]
        for grade in grades:
            assessment = grade.submission.assessment
            rows.append(
                [
                    assessment.course.code,
                    assessment.title,
                    str(grade.score),
                    str(assessment.maximum_score),
                    grade.published_at.strftime("%Y-%m-%d")
                    if grade.published_at
                    else "",
                ]
            )
        if len(rows) == 1:
            rows.append(["No published grades", "", "", "", ""])
        table = Table(rows, repeatRows=1, colWidths=(110, 270, 75, 75, 100))
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d1d5db")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    (
                        "ROWBACKGROUNDS",
                        (0, 1),
                        (-1, -1),
                        [colors.white, colors.HexColor("#f3f4f6")],
                    ),
                    ("PADDING", (0, 0), (-1, -1), 7),
                ]
            )
        )
        story.append(table)
        document.build(story)
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="transcript.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response
