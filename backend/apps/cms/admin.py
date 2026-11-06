from django.contrib import admin

from .models import FAQ, BlogPost, ContentPage


@admin.register(ContentPage)
class ContentPageAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "published_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}  # noqa: RUF012


@admin.register(FAQ)
class FAQAdmin(admin.ModelAdmin):
    list_display = ("question", "position", "is_published")
    list_filter = ("is_published",)
    search_fields = ("question", "answer")


@admin.register(BlogPost)
class BlogPostAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "published_at")
    list_filter = ("is_published",)
    search_fields = ("title", "slug")
    prepopulated_fields = {"slug": ("title",)}  # noqa: RUF012
