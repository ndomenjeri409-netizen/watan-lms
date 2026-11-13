from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.enrollment.models import Enrollment
from common.audit import get_object_audit_scope, record_audit

from .models import Assessment, Grade, GradeRevision, GradeSupersession


def final_exam_grades_approved(class_group_id):
    exam_ids = list(
        Assessment.objects.filter(
            class_group_id=class_group_id, template__kind=Assessment.Kind.EXAM
        ).values_list("id", flat=True)
    )
    enrollments = Enrollment.objects.filter(
        class_group_id=class_group_id, status=Enrollment.Status.ACTIVE
    )
    enrollment_ids = list(enrollments.values_list("id", flat=True))
    if not exam_ids or not enrollment_ids:
        return False

    expected = {
        (exam_id, enrollment_id)
        for exam_id in exam_ids
        for enrollment_id in enrollment_ids
    }
    published_grades = set(
        Grade.objects.filter(
            assessment_id__in=exam_ids,
            enrollment_id__in=enrollment_ids,
            official_revision__status=Grade.Status.PUBLISHED,
        ).values_list("assessment_id", "enrollment_id")
    )
    return expected.issubset(published_grades)


def record_grade_revision(*, grade, actor, change_note="", attempt_grant=None):
    revision = GradeRevision.objects.create(
        grade=grade,
        revision=grade.revision,
        submission=grade.submission,
        source=grade.source,
        attempt_number=(
            grade.submission.attempt_number if grade.submission_id else None
        ),
        score=grade.score,
        feedback=grade.feedback,
        status=grade.status,
        changed_by=actor,
        change_note=change_note,
        approved_by=grade.approved_by,
        approved_at=grade.approved_at,
        published_by=grade.published_by,
        published_at=grade.published_at,
        review_note=grade.review_note,
        is_late=grade.submission.is_late if grade.submission_id else False,
        attempt_grant=attempt_grant,
    )
    unit, group_level = get_object_audit_scope(revision)
    record_audit(
        actor=actor,
        action="grade_revision_created",
        obj=revision,
        unit=unit,
        group_level=group_level,
        after={
            "grade_id": str(grade.id),
            "revision": revision.revision,
            "score": str(revision.score) if revision.score is not None else None,
            "status": revision.status,
            "source": revision.source,
        },
    )
    return revision


def transition_grade(*, grade_id, actor, action, note="", revision_id=None):
    if action == "approve_and_publish":
        with transaction.atomic():
            approved = transition_grade(
                grade_id=grade_id,
                actor=actor,
                action="approve",
                note=note,
                revision_id=revision_id,
            )
            return transition_grade(
                grade_id=approved.pk,
                actor=actor,
                action="publish",
                note=note,
            )

    with transaction.atomic():
        grade = (
            Grade.objects.select_for_update(of=("self",))
            .select_related(
                "assessment__template__course",
                "assessment__class_group",
                "enrollment__student",
                "official_revision",
            )
            .get(pk=grade_id)
        )
        latest = (
            GradeRevision.objects.select_for_update(of=("self",))
            .filter(grade=grade)
            .order_by("-revision")
            .first()
        )
        if latest is None or (revision_id is not None and latest.pk != revision_id):
            raise ValidationError(
                {"revision": "Only the latest grade revision can be changed."}
            )
        assessment = grade.assessment
        grant = latest.attempt_grant
        if assessment.class_group_id:
            from apps.scheduling.models import ClassGroup

            class_group = ClassGroup.objects.select_for_update().get(
                pk=assessment.class_group_id
            )
            if class_group.status in {
                ClassGroup.Status.COMPLETED,
                ClassGroup.Status.CANCELLED,
            } and (
                grant is None
                or grant.valid_until <= timezone.now()
                or grant.assessment_id != assessment.id
                or grant.enrollment_id != grade.enrollment_id
            ):
                raise ValidationError(
                    {"class_group": "Grades cannot change after the class is locked."}
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
            if grade.score is None:
                raise ValidationError({"score": "A score is required for approval."})
            grade.status = Grade.Status.PENDING_APPROVAL
            grade.review_note = ""
        elif action == "approve":
            if grade.status != Grade.Status.PENDING_APPROVAL:
                raise ValidationError(
                    {"status": "Only grades awaiting approval can be approved."}
                )
            grade.status = Grade.Status.APPROVED
            grade.approved_by = actor
            grade.approved_at = timezone.now()
            grade.review_note = ""
        elif action == "publish":
            if grade.status != Grade.Status.APPROVED:
                raise ValidationError(
                    {"status": "Only approved grade revisions can be published."}
                )
            grade.status = Grade.Status.PUBLISHED
            grade.published_by = actor
            grade.published_at = timezone.now()
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
            grade.published_by = None
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
                "published_by",
                "published_at",
                "revision",
                "updated_at",
            )
        )
        revision = record_grade_revision(
            grade=grade,
            actor=actor,
            change_note=note,
            attempt_grant=grant,
        )
        unit, group_level = get_object_audit_scope(revision)
        record_audit(
            actor=actor,
            action=f"grade_{action}",
            obj=revision,
            unit=unit,
            group_level=group_level,
            before=before,
            after={
                "status": grade.status,
                "revision": grade.revision,
                "score": str(grade.score) if grade.score is not None else None,
                "review_note": grade.review_note,
                "grade_id": str(grade.id),
            },
        )
        if action == "publish":
            previous_revision = grade.official_revision
            if previous_revision:
                from .transcripts import snapshot_transcript

                snapshot_transcript(
                    student=grade.enrollment.student,
                    generated_by=actor,
                )
                GradeSupersession.objects.create(
                    grade=grade,
                    previous_revision=previous_revision,
                    replacement_revision=revision,
                    superseded_by=actor,
                )
                unit, group_level = get_object_audit_scope(grade)
                record_audit(
                    actor=actor,
                    action="grade_revision_superseded",
                    obj=grade,
                    unit=unit,
                    group_level=group_level,
                    before={"revision_id": str(previous_revision.id)},
                    after={"revision_id": str(revision.id)},
                )
            grade.official_revision = revision
            grade.save(update_fields=("official_revision", "updated_at"))
            from .transcripts import snapshot_transcript

            snapshot_transcript(
                student=grade.enrollment.student,
                generated_by=actor,
                trigger_revision=revision,
                is_revised=previous_revision is not None,
            )
            if (
                assessment.kind == Assessment.Kind.EXAM
                and assessment.class_group_id
                and final_exam_grades_approved(assessment.class_group_id)
            ):
                from apps.scheduling.models import ClassGroup
                from apps.scheduling.services import transition_class_group

                class_group = ClassGroup.objects.get(pk=assessment.class_group_id)
                if class_group.status == ClassGroup.Status.RUNNING:
                    transition_class_group(
                        class_group_id=class_group.pk,
                        target=ClassGroup.Status.COMPLETED,
                        actor=actor,
                    )
        grade.refresh_from_db()
        return grade
