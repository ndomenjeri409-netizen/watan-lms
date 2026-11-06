from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.files.models import StoredFile
from apps.files.storage import get_storage_client


class Command(BaseCommand):
    help = "Delete storage objects for uploads left pending for more than 24 hours."

    def handle(self, *args, **options):
        cutoff = timezone.now() - timedelta(hours=24)
        client = get_storage_client()
        expired = StoredFile.objects.filter(
            status=StoredFile.Status.PENDING,
            created_at__lt=cutoff,
        )
        removed = 0
        for stored_file in expired.iterator():
            client.delete_object(
                Bucket=settings.R2_BUCKET,
                Key=stored_file.object_key,
            )
            stored_file.status = StoredFile.Status.DELETED
            stored_file.save(update_fields=("status", "updated_at"))
            removed += 1
        self.stdout.write(f"Marked {removed} expired uploads as deleted.")
