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

        user, _ = User.objects.get_or_create(
            firebase_uid=decoded["uid"],
            defaults={
                "email": decoded.get("email", ""),
                "display_name": decoded.get("name", ""),
                "role": None,
            },
        )
        if not user.is_active:
            raise AuthenticationFailed("Account disabled")
        return (user, decoded)

    def authenticate_header(self, request):
        return "Bearer"
