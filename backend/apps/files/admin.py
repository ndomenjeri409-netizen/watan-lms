from django.contrib import admin

from .models import StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ("original_name", "purpose", "status", "owner_user", "size_bytes")
    list_filter = ("purpose", "status")
    search_fields = ("original_name", "object_key")
    readonly_fields = ("object_key", "owner_user", "size_bytes", "created_at")
