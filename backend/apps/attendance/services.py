import hashlib
import secrets
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError

from apps.enrollment.models import Enrollment
from apps.people.models import Student
from common.audit import get_object_audit_scope, record_audit

from .models import AttendanceRecord, AttendanceSession, CheckIn, QrToken


class DuplicateCheckIn(APIException):
    status_code = 409
    default_detail = "Attendance has already been recorded for this session."
    default_code = "duplicate_check_in"


def issue_qr_token(session, actor):
    if not session.is_open:
        raise ValidationError({"session": "This attendance session is closed."})
    raw_token = secrets.token_urlsafe(32)
    with transaction.atomic():
        token = QrToken.objects.create(
            session=session,
            token_digest=hashlib.sha256(raw_token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        unit, group_level = get_object_audit_scope(token)
        record_audit(
            actor=actor,
            action="attendance_qr_issued",
            obj=token,
            unit=unit,
            group_level=group_level,
            after={
                "session_id": str(session.id),
                "expires_at": token.expires_at.isoformat(),
            },
        )
    return raw_token, token


def check_in_with_qr(*, user, raw_token, client_checkin_id=None):
    try:
        student = Student.objects.get(user=user, is_active=True)
    except Student.DoesNotExist as exc:
        raise ValidationError(
            {"student": "An active student profile is required to check in."}
        ) from exc
    digest = hashlib.sha256(raw_token.encode()).hexdigest()
    try:
        token = QrToken.objects.select_related("session__class_group__course").get(
            token_digest=digest
        )
    except QrToken.DoesNotExist as exc:
        raise ValidationError({"token": "This attendance code is invalid."}) from exc
    now = timezone.now()
    session = token.session
    if (
        token.revoked_at
        or token.expires_at <= now
        or not session.is_open
        or session.class_group.status != session.class_group.Status.RUNNING
    ):
        raise ValidationError({"token": "This attendance code has expired."})
    try:
        with transaction.atomic():
            session = (
                AttendanceSession.objects.select_for_update()
                .select_related("class_group")
                .get(pk=session.pk)
            )
            if (
                not session.is_open
                or not session.class_group.is_active
                or session.class_group.status != session.class_group.Status.RUNNING
                or token.revoked_at
                or token.expires_at <= timezone.now()
            ):
                raise ValidationError({"token": "This attendance code has expired."})
            enrollment = (
                Enrollment.objects.select_for_update()
                .filter(
                    student=student,
                    class_group_id=session.class_group_id,
                    status=Enrollment.Status.ACTIVE,
                )
                .first()
            )
            if enrollment is None:
                raise ValidationError(
                    {"student": "You are not on this class's active attendance roster."}
                )
            record = AttendanceRecord.objects.create(session=session, student=student)
            CheckIn.objects.create(
                record=record,
                qr_token=token,
                client_checkin_id=client_checkin_id,
            )
            unit, group_level = get_object_audit_scope(record)
            record_audit(
                actor=user,
                action="attendance_checked_in",
                obj=record,
                unit=unit,
                group_level=group_level,
                after={
                    "session_id": str(session.id),
                    "student_id": str(student.id),
                    "status": record.status,
                    "checked_in_at": record.checked_in_at.isoformat(),
                },
            )
    except IntegrityError as exc:
        raise DuplicateCheckIn() from exc
    return record
