import re
from urllib.parse import urlparse

import boto3
from django.conf import settings
from rest_framework.exceptions import APIException


class StorageNotConfigured(APIException):
    status_code = 503
    default_detail = "Object storage is not configured."
    default_code = "storage_unavailable"


def get_storage_region():
    if settings.STORAGE_REGION:
        return settings.STORAGE_REGION

    host = (urlparse(settings.STORAGE_ENDPOINT_URL).hostname or "").lower()
    backblaze_endpoint = re.fullmatch(r"s3\.([a-z0-9-]+)\.backblazeb2\.com", host)
    if backblaze_endpoint:
        return backblaze_endpoint.group(1)
    return "auto"


def get_storage_client():
    required = (
        settings.STORAGE_ENDPOINT_URL,
        settings.STORAGE_BUCKET,
        settings.STORAGE_ACCESS_KEY_ID,
        settings.STORAGE_SECRET_ACCESS_KEY,
    )
    if not all(required):
        raise StorageNotConfigured()
    return boto3.client(
        "s3",
        endpoint_url=settings.STORAGE_ENDPOINT_URL,
        aws_access_key_id=settings.STORAGE_ACCESS_KEY_ID,
        aws_secret_access_key=settings.STORAGE_SECRET_ACCESS_KEY,
        region_name=get_storage_region(),
    )
