from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from common.audit import get_object_audit_scope, record_audit

from .models import Grade, GradeRevision


def record_grade_revision(*, grade, actor, change_note=""):
    GradeRevision.objects.create(
        grade=grade,
        revision=grade.revision,
        score=grade.score,
        feedback=grade.feedback,
        status=grade.status,
        changed_by=actor,
        change_note=change_note,
    )
    unit, group_level = get_object_audit_scope(grade)
    record_audit(
        actor=actor,
        action="grade_revision_created",
        obj=grade,
        unit=unit,
        group_level=group_level,
        after={
            "revision": grade.revision,
            "score": str(grade.score),
            "status": grade.status,
        },
    )


def transition_grade(*, grade_id, actor, action, note=""):
    with transaction.atomic():
        grade = (
            Grade.objects.select_for_update()
            .select_related("submission__assessment__course")
            .get(pk=grade_id)
        )
        before = {
            "status": grade.status,
            "revision": grade.revision,
            "score": str(grade.score),
        }
        if action == "submit":
            if grade.status not in {Grade.Status.DRAFT, Grade.Status.REJECTED}:
                raise ValidationError(
                    {"status": "Only draft or returned grades can be submitted."}
                )
            grade.status = Grade.Status.PENDING_APPROVAL
            grade.review_note = ""
        elif action == "approve":
            if grade.status != Grade.Status.PENDING_APPROVAL:
                raise ValidationError(
                    {"status": "Only grades awaiting approval can be published."}
                )
            grade.status = Grade.Status.PUBLISHED
            grade.approved_by = actor
            grade.approved_at = timezone.now()
            grade.published_at = grade.approved_at
            grade.review_note = ""
        elif action == "reject":
            if grade.status != Grade.Status.PENDING_APPROVAL:
                raise ValidationError(
                    {"status": "Only grades awaiting approval can be returned."}
                )
            if not note.strip():
                raise ValidationError(
                    {"note": "Provide a reason when returning a grade."}
                )
            grade.status = Grade.Status.REJECTED
            grade.review_note = note.strip()
            grade.approved_by = None
            grade.approved_at = None
            grade.published_at = None
        else:
            raise ValueError(f"Unknown grade transition: {action}")
        grade.revision += 1
        grade.save(
            update_fields=(
                "status",
                "review_note",
                "approved_by",
                "approved_at",
                "published_at",
                "revision",
                "updated_at",
            )
        )
        record_grade_revision(grade=grade, actor=actor, change_note=note)
        unit, group_level = get_object_audit_scope(grade)
        record_audit(
            actor=actor,
            action=f"grade_{action}",
            obj=grade,
            unit=unit,
            group_level=group_level,
            before=before,
            after={
                "status": grade.status,
                "revision": grade.revision,
                "score": str(grade.score),
                "review_note": grade.review_note,
            },
        )
        return grade
