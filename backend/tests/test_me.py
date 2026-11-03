from unittest.mock import patch

from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.authentication import FirebaseAuthentication
from apps.accounts.models import User


class MeTests(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_missing_header_is_unauthorized(self):
        response = self.client.get("/api/v1/me")
        self.assertEqual(response.status_code, 401)

    @patch("apps.accounts.authentication._ensure_firebase")
    @patch(
        "apps.accounts.authentication.fb_auth.verify_id_token", side_effect=ValueError
    )
    def test_invalid_token_is_unauthorized(self, verify_id_token, ensure_firebase):
        response = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer invalid")
        self.assertEqual(response.status_code, 401)

    @patch("apps.accounts.authentication._ensure_firebase")
    @patch(
        "apps.accounts.authentication.fb_auth.verify_id_token",
        return_value={"uid": "u1", "email": "a@b.com"},
    )
    def test_valid_token_creates_user(self, verify_id_token, ensure_firebase):
        response = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer valid")
        self.assertEqual(response.status_code, 200)
        user = User.objects.get(firebase_uid="u1")
        self.assertIsNone(user.role)
        self.assertEqual(response.json()["email"], "a@b.com")

    @patch("apps.accounts.authentication._ensure_firebase")
    @patch(
        "apps.accounts.authentication.fb_auth.verify_id_token",
        return_value={"uid": "inactive"},
    )
    def test_inactive_user_is_unauthorized(self, verify_id_token, ensure_firebase):
        User.objects.create_user("inactive", is_active=False)
        response = self.client.get("/api/v1/me", HTTP_AUTHORIZATION="Bearer valid")
        self.assertEqual(response.status_code, 401)


class FirebaseAuthenticationTests(TestCase):
    def test_absent_header_does_not_initialize_firebase(self):
        from rest_framework.request import Request
        from rest_framework.test import APIRequestFactory

        request = Request(APIRequestFactory().get("/"))
        with patch("apps.accounts.authentication._ensure_firebase") as ensure:
            self.assertIsNone(FirebaseAuthentication().authenticate(request))
            ensure.assert_not_called()
