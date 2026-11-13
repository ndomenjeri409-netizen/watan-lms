import csv
import hashlib
import io
import logging
import secrets
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from firebase_admin.exceptions import FirebaseError
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    PermissionDenied,
    ValidationError,
)

from apps.accounts import authentication
from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.enrollment.models import Enrollment
from apps.org.models import BusinessUnit
from apps.scheduling.models import ClassGroup
from common.audit import get_object_audit_scope, record_audit

from .models import (
    Student,
    StudentDuplicateCandidate,
    StudentDuplicateLookup,
    StudentEnrollmentGrant,
    allocate_registration_number,
)
from .permissions import can_register_in_unit

logger = logging.getLogger(__name__)

LOOKUP_TOKEN_LIFETIME = timedelta(minutes=10)


def _token_digest(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def find_student_duplicates(values):
    criteria = Q(pk__in=[])
    phone = values.get("phone", "").strip()
    national_id = values.get("national_id", "").strip()
    date_of_birth = values.get("date_of_birth")
    if phone:
        criteria |= Q(phone__iexact=phone)
    if national_id:
        criteria |= Q(national_id__iexact=national_id)
    if date_of_birth and values.get("first_name") and values.get("last_name"):
        criteria |= Q(
            first_name__iexact=values["first_name"].strip(),
            last_name__iexact=values["last_name"].strip(),
            date_of_birth=date_of_birth,
        )
    return Student.objects.filter(criteria).select_related("home_unit").distinct()


def make_duplicate_lookup(actor, unit, candidates):
    raw_token = secrets.token_urlsafe(32)
    lookup = StudentDuplicateLookup.objects.create(
        actor=actor,
        unit=unit,
        token_hash=_token_digest(raw_token),
        expires_at=timezone.now() + LOOKUP_TOKEN_LIFETIME,
    )
    StudentDuplicateCandidate.objects.bulk_create(
        [
            StudentDuplicateCandidate(lookup=lookup, student_id=student_id)
            for student_id in candidates.values_list("pk", flat=True)
        ]
    )
    return raw_token


def lookup_student_duplicate(*, actor, token, phone=None, registration_number=None):
    now = timezone.now()
    with transaction.atomic():
        try:
            lookup = (
                StudentDuplicateLookup.objects.select_for_update()
                .select_related("unit")
                .get(token_hash=_token_digest(token))
            )
        except StudentDuplicateLookup.DoesNotExist as exc:
            raise ValidationError({"token": "This lookup is unavailable."}) from exc
        if not lookup.is_valid(actor, lookup.unit):
            raise ValidationError({"token": "This lookup is expired or already used."})

        candidates = lookup.candidates.select_related("home_unit")
        lookup_method = "phone" if phone is not None else "registration_number"
        if phone is not None:
            matches = candidates.filter(phone__iexact=phone.strip()).distinct()
        else:
            matches = candidates.filter(
                registration_number__iexact=registration_number.strip()
            ).distinct()
        matched_students = list(matches[:20])
        lookup.used_at = now
        lookup.save(update_fields=("used_at", "updated_at"))
        record_audit(
            actor=actor,
            action="student_duplicate_lookup",
            obj=lookup,
            unit=lookup.unit,
            after={"method": lookup_method, "match_count": len(matched_students)},
        )

        results = []
        for student in matched_students:
            raw_enrollment_token = secrets.token_urlsafe(32)
            StudentEnrollmentGrant.objects.create(
                actor=actor,
                unit=lookup.unit,
                student=student,
                token_hash=_token_digest(raw_enrollment_token),
                expires_at=now + LOOKUP_TOKEN_LIFETIME,
            )
            results.append(
                {
                    "name": f"{student.first_name} {student.last_name}",
                    "home_unit": student.home_unit.code,
                    "registration_number": student.registration_number,
                    "enrollment_token": raw_enrollment_token,
                }
            )
        return results


def enroll_student_in_unit(
    *, actor, class_group, student=None, enrollment_token=None, allow_unlisted=False
):
    with transaction.atomic():
        class_group = ClassGroup.objects.select_related(
            "course__department", "course__unit"
        ).get(pk=class_group.pk)
        unit = class_group.course.unit
        if not can_register_in_unit(actor, unit, class_group.course.department_id):
            raise PermissionDenied("You may not enroll students in this unit.")
        if (
            not class_group.is_active
            or class_group.status
            not in {ClassGroup.Status.OPEN, ClassGroup.Status.RUNNING}
            or not class_group.course.is_active
            or class_group.course.status != class_group.course.Status.PUBLISHED
        ):
            raise ValidationError(
                {"class_group": "Select an open class for a published course."}
            )

        grant = None
        if enrollment_token:
            try:
                grant = StudentEnrollmentGrant.objects.select_for_update().get(
                    token_hash=_token_digest(enrollment_token)
                )
            except StudentEnrollmentGrant.DoesNotExist as exc:
                raise ValidationError(
                    {"enrollment_token": "This enrollment action is unavailable."}
                ) from exc
            if (
                grant.actor_id != actor.pk
                or grant.unit_id != unit.pk
                or grant.used_at is not None
                or grant.expires_at <= timezone.now()
            ):
                raise ValidationError(
                    {
                        "enrollment_token": (
                            "This enrollment action is expired or already used."
                        )
                    }
                )
            student = Student.objects.select_for_update().get(pk=grant.student_id)
        elif student is not None:
            if not allow_unlisted:
                student = (
                    Student.objects.for_user(actor)
                    .select_for_update(of=("self",))
                    .filter(pk=student.pk)
                    .first()
                )
                if student is None:
                    raise PermissionDenied("You may not access this student.")
            else:
                student = Student.objects.select_for_update().get(pk=student.pk)
        else:
            raise ValidationError(
                "Select a visible student or provide an enrollment token."
            )

        existing = Enrollment.objects.filter(
            student=student, course=class_group.course
        ).first()
        if existing:
            if (
                existing.status == Enrollment.Status.ACTIVE
                and existing.class_group_id == class_group.pk
            ):
                if grant is not None:
                    grant.used_at = timezone.now()
                    grant.save(update_fields=("used_at", "updated_at"))
                return existing
            raise ValidationError(
                {"student": "This student already has an enrollment in the course."}
            )

        enrollment = Enrollment.objects.create(
            student=student,
            course=class_group.course,
            unit=unit,
        )
        from apps.enrollment.services import transition_enrollment

        enrollment = transition_enrollment(
            enrollment, Enrollment.Status.APPROVED, actor
        )
        enrollment = transition_enrollment(
            enrollment,
            Enrollment.Status.ACTIVE,
            actor,
            class_group_id=class_group.pk,
        )
        if grant is not None:
            grant.used_at = timezone.now()
            grant.save(update_fields=("used_at", "updated_at"))
        if student.status == Student.Status.APPLICANT:
            before_status = student.status
            student.status = Student.Status.ACTIVE
            student.save(update_fields=("status", "updated_at"))
            unit, group_level = get_object_audit_scope(student)
            record_audit(
                actor=actor,
                action="student_status_changed",
                obj=student,
                unit=unit,
                group_level=group_level,
                before={"status": before_status},
                after={"status": student.status, "reason": "enrollment activated"},
            )
        return enrollment


def register_student(*, values, actor):
    unit = values["unit"]
    class_group = values["class_group"]
    department = class_group.course.department
    with transaction.atomic():
        year = timezone.localdate().year
        student = Student.objects.create(
            department=department,
            home_unit=unit,
            program=values.get("program"),
            registration_number=allocate_registration_number(
                unit, year, department=department
            ),
            first_name=values["first_name"],
            last_name=values["last_name"],
            email=values.get("email", ""),
            phone=values["phone"],
            date_of_birth=values.get("date_of_birth"),
            national_id=values.get("national_id", ""),
            photo_file=values.get("photo_file"),
            admission_year=year,
            status=Student.Status.ACTIVE,
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
                "home_unit_id": str(student.home_unit_id),
                "department_id": str(student.department_id),
                "status": student.status,
                "account_status": student.account_status,
            },
        )
        enrollment = enroll_student_in_unit(
            actor=actor,
            class_group=class_group,
            student=student,
            allow_unlisted=True,
        )
        return student, enrollment


def transfer_student(*, student, target_unit, actor):
    if not target_unit.is_active:
        raise ValidationError({"home_unit": "Select an active unit."})
    if not (
        actor.has_role_global(Role.SUPER_ADMIN, Role.ADMIN)
        or actor.has_role_for_unit(Role.UNIT_MANAGER, target_unit.pk)
    ):
        raise PermissionDenied(
            "Only the target unit manager, ADMIN, or SUPER_ADMIN may transfer a student."
        )
    with transaction.atomic():
        student = Student.objects.select_for_update().get(pk=student.pk)
        if student.home_unit_id == target_unit.pk:
            raise ValidationError(
                {"home_unit": "The student is already registered in this unit."}
            )
        before = {
            "home_unit_id": str(student.home_unit_id),
            "registration_number": student.registration_number,
        }
        student.home_unit = target_unit
        student._allow_home_unit_transfer = True
        student.save(update_fields=("home_unit", "updated_at"))
        record_audit(
            actor=actor,
            action="student_transferred",
            obj=student,
            unit=target_unit,
            before=before,
            after={
                "home_unit_id": str(student.home_unit_id),
                "registration_number": student.registration_number,
            },
        )
    return student


def change_student_status(*, student, status, reason, actor):
    if not reason.strip():
        raise ValidationError({"reason": "Provide a reason for the status change."})
    with transaction.atomic():
        student = Student.objects.select_for_update().get(pk=student.pk)
        if student.status == status:
            raise ValidationError({"status": "The student already has this status."})
        before = {"status": student.status}
        student.status = status
        student.save(update_fields=("status", "updated_at"))
        unit, group_level = get_object_audit_scope(student)
        record_audit(
            actor=actor,
            action="student_status_changed",
            obj=student,
            unit=unit,
            group_level=group_level,
            before=before,
            after={"status": status, "reason": reason.strip()},
        )
    return student


def import_student_csv(upload, request):
    try:
        content = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationError(
            {"file": "The CSV file must use UTF-8 encoding."}
        ) from exc

    reader = csv.DictReader(io.StringIO(content))
    required_headers = {
        "unit_code",
        "class_code",
        "first_name",
        "last_name",
        "phone",
    }
    headers = {header.strip().lower() for header in (reader.fieldnames or [])}
    missing_headers = required_headers - headers
    if missing_headers:
        raise ValidationError(
            {
                "file": (
                    "Missing required columns: " + ", ".join(sorted(missing_headers))
                )
            }
        )

    from .serializers import StudentRegistrationSerializer

    created = 0
    row_errors = []
    try:
        for line_number, row in enumerate(reader, start=2):
            normalized = {
                (key or "").strip().lower(): (value or "").strip()
                for key, value in row.items()
                if key is not None
            }
            unit = BusinessUnit.objects.filter(
                code__iexact=normalized.get("unit_code", ""), is_active=True
            ).first()
            class_group = (
                ClassGroup.objects.filter(
                    code__iexact=normalized.get("class_code", ""),
                    course__unit=unit,
                ).first()
                if unit
                else None
            )
            if unit is None or class_group is None:
                row_errors.append(
                    {
                        "row": line_number,
                        "message": "Select a valid unit_code and class_code.",
                    }
                )
                continue

            values = {
                "unit": str(unit.pk),
                "class_group": str(class_group.pk),
                "first_name": normalized.get("first_name", ""),
                "last_name": normalized.get("last_name", ""),
                "phone": normalized.get("phone", ""),
                "email": normalized.get("email", ""),
                "date_of_birth": normalized.get("date_of_birth") or None,
                "national_id": normalized.get("national_id", ""),
            }
            serializer = StudentRegistrationSerializer(
                data=values, context={"request": request}
            )
            if not serializer.is_valid():
                row_errors.append(
                    {"row": line_number, "message": str(serializer.errors)}
                )
                continue

            data = serializer.validated_data
            matches = find_student_duplicates(data)
            visible_match = (
                Student.objects.for_user(request.user)
                .filter(pk__in=matches.values("pk"))
                .exists()
            )
            if visible_match:
                row_errors.append(
                    {
                        "row": line_number,
                        "message": "A possible duplicate requires manual review.",
                    }
                )
                continue
            if matches.exists():
                row_errors.append(
                    {
                        "row": line_number,
                        "message": "A possible match exists in another unit.",
                    }
                )
                continue

            try:
                register_student(values=data, actor=request.user)
            except ValidationError as exc:
                row_errors.append({"row": line_number, "message": str(exc.detail)})
                continue
            created += 1
    except csv.Error as exc:
        raise ValidationError({"file": "The CSV file is malformed."}) from exc

    return {"created": created, "row_errors": row_errors}


class IdentityProvisioningUnavailable(APIException):
    status_code = 503
    default_detail = "Student identity provisioning is unavailable."
    default_code = "identity_provisioning_unavailable"


def invite_student(student, actor, request, email=None):
    firebase_uid = None
    with transaction.atomic():
        student = Student.objects.select_for_update().get(pk=student.pk)
        if (
            student.user_id is not None
            or student.account_status != Student.AccountStatus.NONE
        ):
            raise ValidationError(
                {"account_status": "This student already has an account."}
            )

        email = email or student.email
        if not email:
            raise ValidationError(
                {"email": "An email is required to invite this student."}
            )
        if User.objects.filter(email__iexact=email).exists():
            raise ValidationError(
                {"email": "An account already exists for this email."}
            )

        try:
            authentication._ensure_firebase()
        except (AuthenticationFailed, ValueError, FirebaseError) as exc:
            raise IdentityProvisioningUnavailable() from exc

        authentication.verify_revoked_token(request)
        try:
            firebase_user = authentication.fb_auth.create_user(
                email=email,
                display_name=f"{student.first_name} {student.last_name}",
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
                email=email,
                display_name=f"{student.first_name} {student.last_name}",
                role=Role.STUDENT,
                granted_by=actor,
            )
            before = {
                "email": student.email,
                "user_id": None,
                "account_status": student.account_status,
            }
            student.email = email
            student.user = user
            student.account_status = Student.AccountStatus.INVITED
            student.save(
                update_fields=("email", "user", "account_status", "updated_at")
            )
            unit, group_level = get_object_audit_scope(student)
            record_audit(
                actor=actor,
                action="student_invited",
                obj=student,
                unit=unit,
                group_level=group_level,
                before=before,
                after={
                    "email": email,
                    "user_id": str(user.id),
                    "account_status": student.account_status,
                },
            )
        except Exception:
            try:
                authentication.fb_auth.delete_user(firebase_uid)
            except FirebaseError:
                logger.exception(
                    "Could not remove Firebase user after failed student invite."
                )
            raise

    return student
