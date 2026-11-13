from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.people.models import Student, allocate_registration_number
from apps.scheduling.models import ClassGroup
from common.audit import get_object_audit_scope, record_audit

from .models import Application, CourseAccess, Enrollment

ALLOWED_TRANSITIONS = {
    Enrollment.Status.PENDING: {
        Enrollment.Status.APPROVED,
        Enrollment.Status.REJECTED,
        Enrollment.Status.CANCELLED,
    },
    Enrollment.Status.APPROVED: {
        Enrollment.Status.ACTIVE,
        Enrollment.Status.REJECTED,
        Enrollment.Status.CANCELLED,
    },
    Enrollment.Status.ACTIVE: {
        Enrollment.Status.COMPLETED,
        Enrollment.Status.CANCELLED,
    },
    Enrollment.Status.COMPLETED: set(),
    Enrollment.Status.REJECTED: set(),
    Enrollment.Status.CANCELLED: set(),
}


def transition_enrollment(enrollment, target, actor, class_group_id=None):
    with transaction.atomic():
        enrollment = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
        if target not in ALLOWED_TRANSITIONS.get(enrollment.status, set()):
            raise ValidationError(
                {
                    "status": f"Cannot move an enrollment from {enrollment.status} to {target}."
                }
            )
        if target == Enrollment.Status.ACTIVE:
            selected_class_id = class_group_id or enrollment.class_group_id
            if not selected_class_id:
                raise ValidationError(
                    {
                        "class_group": "Assign the enrollment to a class before activation."
                    }
                )
            try:
                class_group = ClassGroup.objects.select_for_update().get(
                    pk=selected_class_id
                )
            except ClassGroup.DoesNotExist as exc:
                raise ValidationError(
                    {"class_group": "Select an existing class."}
                ) from exc
            if class_group.course_id != enrollment.course_id:
                raise ValidationError(
                    {"class_group": "The class must use the enrollment's course."}
                )
            if class_group.course.unit_id != enrollment.unit_id:
                raise ValidationError(
                    {
                        "class_group": "The class must use the enrollment's business unit."
                    }
                )
            if not class_group.is_active or class_group.status in {
                ClassGroup.Status.COMPLETED,
                ClassGroup.Status.CANCELLED,
            }:
                raise ValidationError({"class_group": "Select an active class."})
            active_count = (
                Enrollment.objects.filter(
                    class_group=class_group, status=Enrollment.Status.ACTIVE
                )
                .exclude(pk=enrollment.pk)
                .count()
            )
            if active_count >= class_group.capacity:
                raise ValidationError(
                    {"class_group": "This class has reached its enrollment capacity."}
                )
        elif class_group_id:
            raise ValidationError(
                {
                    "class_group": "A class may only be assigned when activating an enrollment."
                }
            )

        before = {
            "status": enrollment.status,
            "class_group_id": (
                str(enrollment.class_group_id) if enrollment.class_group_id else None
            ),
        }
        enrollment.status = target
        update_fields = ["status", "updated_at"]
        if target == Enrollment.Status.APPROVED:
            enrollment.approved_by = actor
            update_fields.append("approved_by")
        if target == Enrollment.Status.ACTIVE:
            enrollment.class_group = class_group
            update_fields.append("class_group")
            enrollment.activated_at = timezone.now()
            update_fields.append("activated_at")
        enrollment.save(update_fields=update_fields)
        unit, group_level = get_object_audit_scope(enrollment)
        record_audit(
            actor=actor,
            action="enrollment_status_changed",
            obj=enrollment,
            unit=unit,
            group_level=group_level,
            before=before,
            after={"status": target},
        )
        if target == Enrollment.Status.ACTIVE:
            access, created = CourseAccess.objects.get_or_create(
                student=enrollment.student,
                course=enrollment.course,
                defaults={"enrollment": enrollment},
            )
            if not created and (
                not access.is_active or access.enrollment_id != enrollment.id
            ):
                access.enrollment = enrollment
                access.is_active = True
                access.save(update_fields=("enrollment", "is_active", "updated_at"))
            unit, group_level = get_object_audit_scope(access)
            record_audit(
                actor=actor,
                action="course_access_granted",
                obj=access,
                unit=unit,
                group_level=group_level,
                after={
                    "student_id": str(enrollment.student_id),
                    "course_id": str(enrollment.course_id),
                    "is_active": True,
                },
            )
        elif target in {Enrollment.Status.CANCELLED, Enrollment.Status.COMPLETED}:
            for access in CourseAccess.objects.select_for_update().filter(
                enrollment=enrollment, is_active=True
            ):
                access.is_active = False
                access.save(update_fields=("is_active", "updated_at"))
                unit, group_level = get_object_audit_scope(access)
                record_audit(
                    actor=actor,
                    action="course_access_revoked",
                    obj=access,
                    unit=unit,
                    group_level=group_level,
                    before={"is_active": True},
                    after={"is_active": False},
                )
    return enrollment


def approve_application(application, actor):
    with transaction.atomic():
        application = (
            Application.objects.select_for_update(of=("self",))
            .select_related("department", "program", "course")
            .get(pk=application.pk)
        )
        if application.status != Application.Status.PENDING:
            raise ValidationError(
                {"status": "Only pending applications can be approved."}
            )
        year = timezone.localdate().year
        student = Student.objects.create(
            department=application.department,
            home_unit=application.department.unit,
            program=application.program,
            registration_number=allocate_registration_number(
                application.department.unit,
                year,
                department=application.department,
            ),
            first_name=application.first_name,
            last_name=application.last_name,
            email=application.email,
            phone=application.phone,
            admission_year=year,
            account_status=Student.AccountStatus.NONE,
        )
        unit, group_level = get_object_audit_scope(student)
        record_audit(
            actor=actor,
            action="student_registered",
            obj=student,
            unit=unit,
            group_level=group_level,
            after={
                "registration_number": student.registration_number,
                "user_id": None,
                "account_status": student.account_status,
                "department_id": str(student.department_id),
            },
        )
        enrollment = Enrollment.objects.create(
            student=student,
            course=application.course,
            unit=application.course.unit,
            application=application,
        )
        transition_enrollment(enrollment, Enrollment.Status.APPROVED, actor)
        before = {"status": application.status}
        application.status = Application.Status.APPROVED
        application.student = student
        application.reviewed_by = actor
        application.reviewed_at = timezone.now()
        application.save(
            update_fields=(
                "status",
                "student",
                "reviewed_by",
                "reviewed_at",
                "updated_at",
            )
        )
        unit, group_level = get_object_audit_scope(application)
        record_audit(
            actor=actor,
            action="application_approved",
            obj=application,
            unit=unit,
            group_level=group_level,
            before=before,
            after={
                "status": application.status,
                "student_id": str(student.id),
                "enrollment_id": str(enrollment.id),
            },
        )
    return application, student, enrollment


def reject_application(application, actor, note=""):
    with transaction.atomic():
        application = Application.objects.select_for_update().get(pk=application.pk)
        if application.status != Application.Status.PENDING:
            raise ValidationError(
                {"status": "Only pending applications can be rejected."}
            )
        before = {"status": application.status}
        application.status = Application.Status.REJECTED
        application.reviewed_by = actor
        application.reviewed_at = timezone.now()
        application.review_note = note
        application.save(
            update_fields=(
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
                "updated_at",
            )
        )
        unit, group_level = get_object_audit_scope(application)
        record_audit(
            actor=actor,
            action="application_rejected",
            obj=application,
            unit=unit,
            group_level=group_level,
            before=before,
            after={"status": application.status, "review_note": note},
        )
    return application


def record_public_application(application):
    unit, group_level = get_object_audit_scope(application)
    record_audit(
        system_label="public_application_submission",
        action="application_submitted",
        obj=application,
        unit=unit,
        group_level=group_level,
        after={
            "course_id": str(application.course_id),
            "department_id": str(application.department_id),
            "status": application.status,
        },
    )
