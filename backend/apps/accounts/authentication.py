import json

import firebase_admin
from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension
from firebase_admin import auth as fb_auth
from firebase_admin import credentials
from firebase_admin.exceptions import FirebaseError
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from .models import User


class FirebaseAuthScheme(OpenApiAuthenticationExtension):
    target_class = "apps.accounts.authentication.FirebaseAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        return {"type": "http", "scheme": "bearer"}


def _ensure_firebase():
    if not firebase_admin._apps:
        if not settings.FIREBASE_SERVICE_ACCOUNT_JSON:
            raise AuthenticationFailed("Firebase authentication is not configured.")
        cred = credentials.Certificate(
            json.loads(settings.FIREBASE_SERVICE_ACCOUNT_JSON)
        )
        firebase_admin.initialize_app(cred)


def verify_revoked_token(request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthenticationFailed("Administrator session is missing.")
    try:
        decoded = fb_auth.verify_id_token(header[7:], check_revoked=True)
    except (FirebaseError, ValueError) as exc:
        raise AuthenticationFailed("Invalid or revoked administrator session.") from exc
    if decoded.get("uid") != request.user.firebase_uid:
        raise AuthenticationFailed("Administrator session does not match the account.")
    return decoded


def _activate_student_account(user):
    from django.db import transaction

    from apps.people.models import Student
    from common.audit import get_object_audit_scope, record_audit

    student = getattr(user, "student_profile", None)
    if student is None or student.account_status != Student.AccountStatus.INVITED:
        return

    with transaction.atomic():
        student = Student.objects.select_for_update().get(pk=student.pk)
        if student.account_status != Student.AccountStatus.INVITED:
            return

        before = {"account_status": student.account_status}
        student.account_status = Student.AccountStatus.ACTIVE
        student.save(update_fields=("account_status", "updated_at"))
        unit, group_level = get_object_audit_scope(student)
        record_audit(
            actor=user,
            action="student_account_activated",
            obj=student,
            unit=unit,
            group_level=group_level,
            before=before,
            after={"account_status": student.account_status},
        )


class FirebaseAuthentication(BaseAuthentication):
    def authenticate(self, request):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None

        try:
            _ensure_firebase()
            decoded = fb_auth.verify_id_token(header[7:])
        except (FirebaseError, ValueError) as exc:
            raise AuthenticationFailed("Invalid or expired session") from exc

        user, _ = User.objects.select_related("student_profile").get_or_create(
            firebase_uid=decoded["uid"],
            defaults={
                "email": decoded.get("email", ""),
                "display_name": decoded.get("name", ""),
            },
        )
        if not user.is_active:
            raise AuthenticationFailed("Account disabled")
        _activate_student_account(user)
        return (user, decoded)

    def authenticate_header(self, request):
        return "Bearer"
