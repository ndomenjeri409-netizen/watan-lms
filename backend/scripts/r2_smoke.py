import uuid
from urllib.request import Request, urlopen

import boto3
from django.conf import settings


def main():
    if not all(
        (
            settings.R2_ENDPOINT_URL,
            settings.R2_BUCKET,
            settings.R2_ACCESS_KEY_ID,
            settings.R2_SECRET_ACCESS_KEY,
        )
    ):
        raise RuntimeError("Configure all R2 settings before running this smoke test.")

    client = boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )
    key = f"smoke-tests/{uuid.uuid4()}.txt"
    payload = b"Watan LMS R2 connectivity check."
    put_url = client.generate_presigned_url(
        "put_object",
        Params={"Bucket": settings.R2_BUCKET, "Key": key},
        ExpiresIn=300,
    )
    uploaded = False
    try:
        with urlopen(Request(put_url, data=payload, method="PUT")) as response:
            if response.status not in (200, 201):
                raise RuntimeError(
                    f"Presigned upload failed with HTTP {response.status}."
                )
            uploaded = True

        client.head_object(Bucket=settings.R2_BUCKET, Key=key)
        get_url = client.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.R2_BUCKET, "Key": key},
            ExpiresIn=300,
        )
        with urlopen(get_url) as response:
            if response.read() != payload:
                raise RuntimeError(
                    "Downloaded R2 object did not match uploaded content."
                )
    finally:
        if uploaded:
            client.delete_object(Bucket=settings.R2_BUCKET, Key=key)
    print("R2 presigned PUT, HEAD, GET, and DELETE passed.")


if __name__ == "__main__":
    import os

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
    import django

    django.setup()
    main()
