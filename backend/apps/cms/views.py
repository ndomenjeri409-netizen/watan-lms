from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from common.audit import record_audit
from common.scoping import ScopedViewSetMixin

from .models import FAQ, BlogPost, ContentPage
from .permissions import CMSPermission
from .serializers import BlogPostSerializer, ContentPageSerializer, FAQSerializer


class CMSViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = (CMSPermission,)

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            record_audit(
                actor=self.request.user,
                action="created",
                obj=instance,
                unit=None,
                group_level=True,
                after=serializer.data,
            )

    def perform_update(self, serializer):
        before = self.get_serializer(instance=serializer.instance).data
        with transaction.atomic():
            instance = serializer.save()
            record_audit(
                actor=self.request.user,
                action="updated",
                obj=instance,
                unit=None,
                group_level=True,
                before=before,
                after=self.get_serializer(instance=instance).data,
            )

    def perform_destroy(self, instance):
        before = self.get_serializer(instance=instance).data
        with transaction.atomic():
            instance.is_published = False
            instance.save(update_fields=("is_published", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="unpublished",
                obj=instance,
                unit=None,
                group_level=True,
                before=before,
                after=self.get_serializer(instance=instance).data,
            )


class ContentPageViewSet(CMSViewSet):
    queryset = ContentPage.objects.all()
    serializer_class = ContentPageSerializer
    lookup_field = "slug"
    search_fields = ("title", "body")


class FAQViewSet(CMSViewSet):
    queryset = FAQ.objects.all()
    serializer_class = FAQSerializer
    search_fields = ("question", "answer")
    ordering_fields = ("position", "question")


class BlogPostViewSet(CMSViewSet):
    queryset = BlogPost.objects.all()
    serializer_class = BlogPostSerializer
    lookup_field = "slug"
    search_fields = ("title", "excerpt", "body")
