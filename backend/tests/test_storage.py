from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from apps.files.storage import (
    StorageNotConfigured,
    get_storage_client,
    get_storage_region,
)


class StorageSettingsTests(SimpleTestCase):
    @override_settings(
        STORAGE_ENDPOINT_URL="https://s3.us-west-004.backblazeb2.com",
        STORAGE_REGION="",
    )
    def test_derives_backblaze_signing_region_from_endpoint(self):
        self.assertEqual(get_storage_region(), "us-west-004")

    @override_settings(
        STORAGE_ENDPOINT_URL="https://s3.us-west-004.backblazeb2.com",
        STORAGE_REGION="custom-region",
    )
    def test_explicit_region_overrides_endpoint_region(self):
        self.assertEqual(get_storage_region(), "custom-region")

    @override_settings(
        STORAGE_ENDPOINT_URL="https://example.test",
        STORAGE_REGION="",
    )
    def test_uses_auto_region_for_other_s3_endpoints(self):
        self.assertEqual(get_storage_region(), "auto")

    @override_settings(
        STORAGE_ENDPOINT_URL="https://s3.eu-central-003.backblazeb2.com",
        STORAGE_BUCKET="uploads",
        STORAGE_ACCESS_KEY_ID="test-access-key",
        STORAGE_SECRET_ACCESS_KEY="test-secret-key",
        STORAGE_REGION="",
    )
    @patch("apps.files.storage.boto3.client")
    def test_storage_client_uses_endpoint_derived_region(self, boto_client):
        get_storage_client()

        boto_client.assert_called_once_with(
            "s3",
            endpoint_url="https://s3.eu-central-003.backblazeb2.com",
            aws_access_key_id="test-access-key",
            aws_secret_access_key="test-secret-key",
            region_name="eu-central-003",
        )

    @override_settings(
        STORAGE_ENDPOINT_URL="",
        STORAGE_BUCKET="",
        STORAGE_ACCESS_KEY_ID="",
        STORAGE_SECRET_ACCESS_KEY="",
    )
    def test_missing_storage_configuration_is_reported(self):
        with self.assertRaises(StorageNotConfigured):
            get_storage_client()
