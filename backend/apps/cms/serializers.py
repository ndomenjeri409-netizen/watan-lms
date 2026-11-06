from rest_framework import serializers

from .models import FAQ, BlogPost, ContentPage


class ContentPageSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False)

    class Meta:
        model = ContentPage
        fields = ("id", "title", "slug", "body", "is_published", "published_at")
        read_only_fields = ("id",)


class FAQSerializer(serializers.ModelSerializer):
    class Meta:
        model = FAQ
        fields = ("id", "question", "answer", "position", "is_published")
        read_only_fields = ("id",)


class BlogPostSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False)

    class Meta:
        model = BlogPost
        fields = (
            "id",
            "title",
            "slug",
            "excerpt",
            "body",
            "author_name",
            "is_published",
            "published_at",
        )
        read_only_fields = ("id",)
