from django.db import models
from django.utils.text import slugify

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class PublishedContentQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if user.is_authenticated and user.role in {Role.SUPER_ADMIN, Role.ADMIN}:
            return self
        return self.filter(is_published=True)


class ContentPage(BaseModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    body = models.TextField()
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = PublishedContentQuerySet.as_manager()

    class Meta:
        ordering = ("title",)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class FAQ(BaseModel):
    question = models.CharField(max_length=500)
    answer = models.TextField()
    position = models.PositiveIntegerField(default=0)
    is_published = models.BooleanField(default=False)

    objects = PublishedContentQuerySet.as_manager()

    class Meta:
        ordering = ("position", "question")

    def __str__(self):
        return self.question


class BlogPost(BaseModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    excerpt = models.CharField(max_length=500, blank=True)
    body = models.TextField()
    author_name = models.CharField(max_length=160, blank=True)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = PublishedContentQuerySet.as_manager()

    class Meta:
        ordering = ("-published_at", "title")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title
