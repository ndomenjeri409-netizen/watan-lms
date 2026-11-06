import boto3
from django.conf import settings
from rest_framework.exceptions import APIException


class StorageNotConfigured(APIException):
    status_code = 503
    default_detail = "Object storage is not configured."
    default_code = "storage_unavailable"


def get_storage_client():
    required = (
        settings.R2_ENDPOINT_URL,
        settings.R2_BUCKET,
        settings.R2_ACCESS_KEY_ID,
        settings.R2_SECRET_ACCESS_KEY,
    )
    if not all(required):
        raise StorageNotConfigured()
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
