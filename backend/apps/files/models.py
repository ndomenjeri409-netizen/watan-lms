from django.conf import settings
from django.db import models

from common.models import BaseModel


class StoredFile(BaseModel):
    class Purpose(models.TextChoices):
        MATERIAL = "material", "Course material"
        COVER_IMAGE = "cover_image", "Course cover image"
        PROFILE_PHOTO = "profile_photo", "Profile photo"
        DOCUMENT = "document", "Document"
        GENERATED = "generated", "Generated"
        SUBMISSION = "submission", "Assessment submission"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        READY = "READY", "Ready"
        DELETED = "DELETED", "Deleted"

    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    owner_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="stored_files",
    )
    object_key = models.CharField(max_length=512, unique=True)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=120)
    size_bytes = models.PositiveBigIntegerField()
    status = models.CharField(
        max_length=8, choices=Status.choices, default=Status.PENDING
    )

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.original_name
