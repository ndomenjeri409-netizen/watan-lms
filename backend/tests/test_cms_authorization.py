from django.test import TestCase
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.accounts.roles import Role
from apps.cms.models import ContentPage
from tests.helpers import create_role_user


class CMSAuthorizationTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.published_page = ContentPage.objects.create(
            title="Public", slug="public", body="Public content", is_published=True
        )
        self.draft_page = ContentPage.objects.create(
            title="Internal", slug="internal", body="Draft content"
        )

    def test_public_and_unit_scoped_users_only_see_published_content(self):
        response = self.client.get("/api/v1/pages/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["slug"] for item in response.json()["results"]}, {"public"}
        )
        self.assertEqual(
            self.client.get(f"/api/v1/pages/{self.draft_page.slug}/").status_code,
            404,
        )

        manager = create_role_user("cms-manager", role=Role.UNIT_MANAGER)
        self.client.force_authenticate(manager)
        response = self.client.get("/api/v1/pages/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            {item["slug"] for item in response.json()["results"]}, {"public"}
        )

    def test_director_and_auditor_can_read_drafts_but_cannot_write(self):
        for role in (Role.DIRECTOR, Role.AUDITOR):
            user = create_role_user(f"cms-{role.lower()}", role=role)
            self.client.force_authenticate(user)

            response = self.client.get("/api/v1/pages/")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                {item["slug"] for item in response.json()["results"]},
                {"public", "internal"},
            )
            response = self.client.get(f"/api/v1/pages/{self.draft_page.slug}/")
            self.assertEqual(response.status_code, 200)

            response = self.client.post(
                "/api/v1/pages/",
                {"title": "Forbidden", "body": "No write access"},
                format="json",
            )
            self.assertEqual(response.status_code, 403)

    def test_global_admin_can_write_content(self):
        admin = User.objects.create_user("cms-admin", role=Role.ADMIN)
        self.client.force_authenticate(admin)

        response = self.client.post(
            "/api/v1/pages/",
            {"title": "New page", "body": "Created by admin"},
            format="json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertTrue(ContentPage.objects.filter(slug="new-page").exists())
