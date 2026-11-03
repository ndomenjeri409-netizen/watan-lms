from django.db import models


class ScopedQuerySet(models.QuerySet):
    """Every domain queryset implements for_user(); viewsets must call it."""

    def for_user(self, user):
        raise NotImplementedError


class ScopedViewSetMixin:
    """Use on every ModelViewSet to guarantee row-level scoping."""

    def get_queryset(self):
        return super().get_queryset().for_user(self.request.user)
