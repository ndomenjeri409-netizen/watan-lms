from io import BytesIO
from xml.sax.saxutils import escape

from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from apps.assessment.models import Grade, TranscriptVersion
from apps.people.models import Student
from common.audit import get_object_audit_scope, record_audit


def build_transcript_snapshot(student):
    grades = (
        Grade.objects.filter(
            enrollment__student=student,
            official_revision__status=Grade.Status.PUBLISHED,
        )
        .select_related(
            "enrollment__course",
            "official_revision",
        )
        .order_by(
            "enrollment__course__title",
            "assessment__template__title",
        )
    )
    return [
        {
            "course_code": grade.enrollment.course.code,
            "assessment_title": grade.assessment.title,
            "score": str(grade.official_revision.score),
            "maximum_score": str(grade.assessment.maximum_score),
            "published_at": (
                grade.official_revision.published_at.isoformat()
                if grade.official_revision.published_at
                else None
            ),
        }
        for grade in grades
    ]


def snapshot_transcript(
    *, student, generated_by, trigger_revision=None, is_revised=False
):
    snapshot = build_transcript_snapshot(student)
    with transaction.atomic():
        Student.objects.select_for_update().get(pk=student.pk)
        latest = (
            TranscriptVersion.objects.select_for_update()
            .filter(student=student)
            .order_by("-version")
            .first()
        )
        if latest and latest.snapshot == snapshot:
            return latest
        version = TranscriptVersion.objects.create(
            student=student,
            version=latest.version + 1 if latest else 1,
            snapshot=snapshot,
            is_revised=bool(is_revised and latest),
            revision_date=timezone.now() if is_revised and latest else None,
            trigger_revision=trigger_revision,
            generated_by=generated_by,
        )
        unit, group_level = get_object_audit_scope(version)
        record_audit(
            actor=generated_by,
            action="transcript_version_generated",
            obj=version,
            unit=unit,
            group_level=group_level,
            after={
                "version": version.version,
                "is_revised": version.is_revised,
                "trigger_revision_id": (
                    str(trigger_revision.id) if trigger_revision else None
                ),
            },
        )
        return version


def _authorized_student(request, student_id=None):
    students = Student.objects.select_related("department", "user")
    user = request.user
    if student_id is None and user.has_role(Role.STUDENT):
        student = get_object_or_404(students, user=user, is_active=True)
    elif student_id is None:
        raise PermissionDenied("A student id is required for staff transcript access.")
    else:
        student = get_object_or_404(students, pk=student_id)
    allowed = (
        user.has_role_global(*GLOBAL_READ_ROLES)
        or (user.has_role(Role.STUDENT) and student.user_id == user.id)
        or student.department_id in user.department_ids_for_hod()
        or user.has_role_for_unit(Role.UNIT_MANAGER, student.department.unit_id)
    )
    if not allowed:
        raise PermissionDenied("You may not view this student's transcript.")
    return student


def _render_transcript(student, snapshot, version=None):
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
    ]
    if version and version.is_revised:
        revision_date = version.revision_date or version.created_at
        story.extend(
            [
                Spacer(1, 8),
                Paragraph(
                    f"<b>REVISED TRANSCRIPT</b> — {revision_date:%Y-%m-%d}",
                    styles["BodyText"],
                ),
            ]
        )
    story.append(Spacer(1, 16))
    rows = [["Course", "Assessment", "Score", "Maximum", "Published"]]
    rows.extend(
        [
            item["course_code"],
            item["assessment_title"],
            item["score"],
            item["maximum_score"],
            (
                timezone.datetime.fromisoformat(item["published_at"]).strftime(
                    "%Y-%m-%d"
                )
                if item["published_at"]
                else ""
            ),
        ]
        for item in snapshot
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
    return buffer.getvalue()


class StudentTranscriptView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(responses={(200, "application/pdf"): bytes})
    def get(self, request, student_id=None):
        student = _authorized_student(request, student_id)
        version_number = request.query_params.get("version")
        version = None
        if version_number:
            try:
                version = get_object_or_404(
                    TranscriptVersion.objects.filter(student=student),
                    version=int(version_number),
                )
            except ValueError as exc:
                raise PermissionDenied(
                    "Transcript version must be an integer."
                ) from exc
            snapshot = version.snapshot
        else:
            version = (
                TranscriptVersion.objects.filter(student=student)
                .order_by("-version")
                .first()
            )
            snapshot = (
                version.snapshot if version else build_transcript_snapshot(student)
            )
        response = HttpResponse(
            _render_transcript(student, snapshot, version),
            content_type="application/pdf",
        )
        response["Content-Disposition"] = 'attachment; filename="transcript.pdf"'
        response["Cache-Control"] = "private, no-store"
        return response


class TranscriptVersionListView(APIView):
    permission_classes = (IsAuthenticated,)

    @extend_schema(responses={200: dict})
    def get(self, request, student_id=None):
        student = _authorized_student(request, student_id)
        versions = TranscriptVersion.objects.filter(student=student).order_by(
            "-version"
        )
        return Response(
            {
                "versions": [
                    {
                        "version": item.version,
                        "is_revised": item.is_revised,
                        "revision_date": item.revision_date,
                        "created_at": item.created_at,
                    }
                    for item in versions
                ]
            }
        )
