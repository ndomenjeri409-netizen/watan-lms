import uuid
from urllib.request import Request, urlopen

from django.conf import settings

from apps.files.storage import get_storage_client


def main():
    if not all(
        (
            settings.STORAGE_ENDPOINT_URL,
            settings.STORAGE_BUCKET,
            settings.STORAGE_ACCESS_KEY_ID,
            settings.STORAGE_SECRET_ACCESS_KEY,
        )
    ):
        raise RuntimeError(
            "Configure all STORAGE settings before running this smoke test."
        )

    client = get_storage_client()
    key = f"smoke-tests/{uuid.uuid4()}.txt"
    payload = b"Watan LMS object storage connectivity check."
    put_url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.STORAGE_BUCKET, "Key": key},
        ExpiresIn=300,
    )
    uploaded = False
    try:
        with urlopen(Request(put_url, data=payload, method="PUT")) as response:
            uploaded = 200 <= response.status < 300
            if response.status not in (200, 201):
                raise RuntimeError(
                    f"Presigned upload failed with HTTP {response.status}."
                )

        client.head_object(Bucket=settings.STORAGE_BUCKET, Key=key)
        get_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.STORAGE_BUCKET, "Key": key},
            ExpiresIn=300,
        )
        with urlopen(get_url) as response:
            if response.read() != payload:
                raise RuntimeError("Downloaded object did not match uploaded content.")
    finally:
        if uploaded:
            client.delete_object(Bucket=settings.STORAGE_BUCKET, Key=key)
    print("Storage presigned PUT, HEAD, GET, and DELETE passed.")


if __name__ == "__main__":
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()
    main()
