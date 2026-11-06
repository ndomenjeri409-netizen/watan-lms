import logging

from django.db import transaction
from django.utils import timezone
from firebase_admin.exceptions import FirebaseError
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    ValidationError,
)

from apps.accounts import authentication
from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.audit.models import AuditLog
from apps.people.models import Student, allocate_registration_number
from common.audit import get_object_unit, record_audit

from .models import Application, CourseAccess, Enrollment

logger = logging.getLogger(__name__)


class IdentityProvisioningUnavailable(APIException):
    status_code = 503
    default_detail = "Student identity provisioning is unavailable."
    default_code = "identity_provisioning_unavailable"


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


def transition_enrollment(enrollment, target, actor):
    with transaction.atomic():
        enrollment = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
        if target not in ALLOWED_TRANSITIONS.get(enrollment.status, set()):
            raise ValidationError(
                {
                    "status": f"Cannot move an enrollment from {enrollment.status} to {target}."
                }
            )
        before = {"status": enrollment.status}
        enrollment.status = target
        update_fields = ["status", "updated_at"]
        if target == Enrollment.Status.APPROVED:
            enrollment.approved_by = actor
            update_fields.append("approved_by")
        if target == Enrollment.Status.ACTIVE:
            enrollment.activated_at = timezone.now()
            update_fields.append("activated_at")
        enrollment.save(update_fields=update_fields)
        record_audit(
            actor=actor,
            action="enrollment_status_changed",
            instance=enrollment,
            unit=get_object_unit(enrollment),
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
            record_audit(
                actor=actor,
                action="course_access_granted",
                instance=access,
                unit=get_object_unit(access),
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
                record_audit(
                    actor=actor,
                    action="course_access_revoked",
                    instance=access,
                    unit=get_object_unit(access),
                    before={"is_active": True},
                    after={"is_active": False},
                )
    return enrollment


def approve_application(application, actor):
    firebase_uid = None
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
        if User.objects.filter(email__iexact=application.email).exists():
            raise ValidationError(
                {"email": "An account already exists for this applicant email."}
            )
        try:
            authentication._ensure_firebase()
        except (AuthenticationFailed, ValueError, FirebaseError) as exc:
            raise IdentityProvisioningUnavailable() from exc
        try:
            firebase_user = authentication.fb_auth.create_user(
                email=application.email,
                display_name=f"{application.first_name} {application.last_name}",
            )
        except authentication.fb_auth.EmailAlreadyExistsError as exc:
            raise ValidationError(
                {"email": "An identity account already exists for this email."}
            ) from exc
        except FirebaseError as exc:
            raise IdentityProvisioningUnavailable() from exc
        firebase_uid = firebase_user.uid
        try:
            user = User.objects.create_user(
                firebase_uid=firebase_uid,
                email=application.email,
                display_name=f"{application.first_name} {application.last_name}",
                role=Role.STUDENT,
            )
            year = timezone.localdate().year
            student = Student.objects.create(
                user=user,
                department=application.department,
                program=application.program,
                registration_number=allocate_registration_number(
                    application.department, year
                ),
                first_name=application.first_name,
                last_name=application.last_name,
                email=application.email,
                phone=application.phone,
                admission_year=year,
            )
            record_audit(
                actor=actor,
                action="student_provisioned",
                instance=student,
                unit=get_object_unit(student),
                after={
                    "registration_number": student.registration_number,
                    "user_id": str(user.id),
                    "department_id": str(student.department_id),
                },
            )
            enrollment = Enrollment.objects.create(
                student=student,
                course=application.course,
                application=application,
            )
            transition_enrollment(enrollment, Enrollment.Status.APPROVED, actor)
            transition_enrollment(enrollment, Enrollment.Status.ACTIVE, actor)

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
            record_audit(
                actor=actor,
                action="application_approved",
                instance=application,
                unit=get_object_unit(application),
                before=before,
                after={
                    "status": application.status,
                    "student_id": str(student.id),
                    "enrollment_id": str(enrollment.id),
                },
            )
        except Exception:
            try:
                authentication.fb_auth.delete_user(firebase_uid)
            except FirebaseError:
                logger.exception(
                    "Could not remove Firebase user after failed admission."
                )
            raise
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
        record_audit(
            actor=actor,
            action="application_rejected",
            instance=application,
            unit=get_object_unit(application),
            before=before,
            after={"status": application.status, "review_note": note},
        )
    return application


def record_public_application(application):
    AuditLog.objects.create(
        actor=None,
        action="application_submitted",
        object_type=application._meta.label,
        object_id=str(application.pk),
        after={
            "course_id": str(application.course_id),
            "department_id": str(application.department_id),
            "status": application.status,
        },
    )
