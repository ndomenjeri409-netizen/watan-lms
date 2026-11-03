from django.test import TestCase
from rest_framework.test import APIClient


class HealthTests(TestCase):
    def test_healthz_is_available(self):
        response = APIClient().get("/healthz")
        self.assertEqual(response.status_code, 200)

    def test_readyz_checks_database(self):
        response = APIClient().get("/readyz")
        self.assertEqual(response.status_code, 200)
