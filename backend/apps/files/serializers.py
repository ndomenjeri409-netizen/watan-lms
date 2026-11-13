from pathlib import PurePath

from rest_framework import serializers

from apps.accounts.roles import ADMIN_ROLES

from .models import StoredFile
from .policies import UPLOAD_POLICIES


class UploadRequestSerializer(serializers.Serializer):
    purpose = serializers.ChoiceField(choices=StoredFile.Purpose.choices)
    filename = serializers.CharField(max_length=255)
    content_type = serializers.CharField(max_length=120)
    size = serializers.IntegerField(min_value=1)

    def validate(self, attrs):
        purpose = attrs["purpose"]
        policy = UPLOAD_POLICIES.get(purpose)
        if not policy:
            raise serializers.ValidationError(
                {"purpose": "This file purpose cannot be uploaded directly."}
            )
        user = self.context["request"].user
        allowed_roles = policy["roles"]
        if not (
            user.has_role_global(*(allowed_roles & ADMIN_ROLES))
            or user.has_role(*(allowed_roles - ADMIN_ROLES))
        ):
            raise serializers.ValidationError(
                {"purpose": "You may not upload files for this purpose."}
            )
        extension = PurePath(attrs["filename"]).suffix.lower()
        if attrs["content_type"] not in policy["content_types"].get(extension, set()):
            raise serializers.ValidationError(
                {
                    "content_type": "The filename extension and content type are not allowed together."
                }
            )
        if attrs["size"] > policy["max_bytes"]:
            raise serializers.ValidationError(
                {"size": "The file exceeds the maximum allowed size."}
            )
        return attrs


class StoredFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = StoredFile
        fields = (
            "id",
            "purpose",
            "original_name",
            "content_type",
            "size_bytes",
            "status",
            "created_at",
        )
        read_only_fields = fields


class UploadStartedSerializer(serializers.Serializer):
    file = StoredFileSerializer()
    upload_url = serializers.URLField()
    headers = serializers.DictField(child=serializers.CharField())


class DownloadUrlSerializer(serializers.Serializer):
    download_url = serializers.URLField()
    expires_in = serializers.IntegerField()
