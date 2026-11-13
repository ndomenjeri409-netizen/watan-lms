from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.attendance.models import AttendanceSession
from apps.enrollment.models import Enrollment
from common.audit import get_object_audit_scope, record_audit

from .models import ClassGroup, TimetableSlot


def transition_class_group(*, class_group_id, target, actor):
    with transaction.atomic():
        class_group = (
            ClassGroup.objects.select_for_update()
            .select_related("course__department", "course__unit")
            .get(pk=class_group_id)
        )
        if target not in ClassGroup.ALLOWED_STATUS_TRANSITIONS[class_group.status]:
            raise ValidationError(
                {"status": "This class status transition is not allowed."}
            )
        if (
            target == ClassGroup.Status.CANCELLED
            and Enrollment.objects.filter(
                class_group=class_group, status=Enrollment.Status.ACTIVE
            ).exists()
        ):
            raise ValidationError(
                {
                    "status": "Complete or cancel active enrollments before cancelling this class."
                }
            )
        if target == ClassGroup.Status.COMPLETED:
            from apps.assessment.models import Assessment
            from apps.assessment.services import final_exam_grades_approved

            has_final_assessments = Assessment.objects.filter(
                class_group=class_group, template__kind=Assessment.Kind.EXAM
            ).exists()
            if has_final_assessments and not final_exam_grades_approved(class_group.pk):
                raise ValidationError(
                    {
                        "status": "Approve the latest EXAM grade for every active enrollment before completing this class."
                    }
                )
        open_sessions = AttendanceSession.objects.select_for_update().filter(
            class_group=class_group, is_open=True
        )
        if target == ClassGroup.Status.COMPLETED and open_sessions.exists():
            raise ValidationError(
                {
                    "status": "Close open attendance sessions before completing this class."
                }
            )

        before = {"status": class_group.status}
        class_group.status = target
        try:
            class_group.save(update_fields=("status", "updated_at"))
        except DjangoValidationError as exc:
            raise ValidationError(exc.message_dict) from exc

        if target == ClassGroup.Status.CANCELLED:
            closed_at = timezone.now()
            for session in open_sessions:
                session.is_open = False
                session.closed_at = closed_at
                session.save(update_fields=("is_open", "closed_at", "updated_at"))
                unit, group_level = get_object_audit_scope(session)
                record_audit(
                    actor=actor,
                    action="attendance_session_closed",
                    obj=session,
                    unit=unit,
                    group_level=group_level,
                    after={"is_open": False, "closed_at": closed_at.isoformat()},
                )
            for slot in TimetableSlot.objects.select_for_update().filter(
                class_group=class_group, is_active=True
            ):
                slot.is_active = False
                slot.save(update_fields=("is_active", "updated_at"))
                unit, group_level = get_object_audit_scope(slot)
                record_audit(
                    actor=actor,
                    action="archived",
                    obj=slot,
                    unit=unit,
                    group_level=group_level,
                    before={"is_active": True},
                    after={"is_active": False},
                )

        unit, group_level = get_object_audit_scope(class_group)
        record_audit(
            actor=actor,
            action="status_changed",
            obj=class_group,
            unit=unit,
            group_level=group_level,
            before=before,
            after={"status": class_group.status},
        )
        return class_group
