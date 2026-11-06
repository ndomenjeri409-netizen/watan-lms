from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class CourseQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.filter(status=Course.Status.PUBLISHED, is_active=True)
        if user.has_global_read():
            return self

        if user.has_role(Role.STUDENT):
            return self.filter(
                department__students__user=user,
                status=Course.Status.PUBLISHED,
                is_active=True,
            ).distinct()

        unit_ids = user.unit_ids()
        if not unit_ids:
            return self.filter(status=Course.Status.PUBLISHED, is_active=True)

        queryset = self.filter(department__unit_id__in=unit_ids)
        if user.has_role(Role.HOD):
            return queryset.filter(department__role_scopes__user=user).distinct()
        if user.has_role(Role.UNIT_MANAGER):
            return queryset
        if user.has_role(Role.TEACHER):
            return queryset.filter(
                Q(created_by=user) | Q(status=Course.Status.PUBLISHED, is_active=True)
            ).distinct()
        return queryset.filter(status=Course.Status.PUBLISHED, is_active=True)


class Course(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"

    department = models.ForeignKey(
        "org.Department", on_delete=models.PROTECT, related_name="courses"
    )
    program = models.ForeignKey(
        "org.Program",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="courses",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_courses",
    )
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True)
    code = models.CharField(max_length=40, unique=True)
    summary = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    learning_outcomes = models.JSONField(default=list, blank=True)
    cover_image = models.ForeignKey(
        "files.StoredFile",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cover_courses",
    )
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )
    is_active = models.BooleanField(default=True)

    objects = CourseQuerySet.as_manager()

    class Meta:
        ordering = ("title",)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title


class CourseChildQuerySet(ScopedQuerySet):
    course_path = "course"

    def for_user(self, user):
        queryset = self.filter(
            **{f"{self.course_path}__in": Course.objects.for_user(user).values("id")}
        )
        if not user.is_authenticated or user.role not in {
            Role.SUPER_ADMIN,
            Role.ADMIN,
            Role.DIRECTOR,
            Role.HOD,
            Role.TEACHER,
        }:
            return queryset.filter(is_active=True)
        return queryset


class UnitQuerySet(CourseChildQuerySet):
    course_path = "module__course"


class LessonQuerySet(CourseChildQuerySet):
    course_path = "unit__module__course"


class MaterialQuerySet(CourseChildQuerySet):
    course_path = "lesson__unit__module__course"


class CourseModule(BaseModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    objects = CourseChildQuerySet.as_manager()

    class Meta:
        ordering = ("position", "title")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("course", "position"), name="unique_module_position_per_course"
            )
        ]

    def __str__(self):
        return self.title


class Unit(BaseModel):
    module = models.ForeignKey(
        CourseModule, on_delete=models.CASCADE, related_name="units"
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)

    objects = UnitQuerySet.as_manager()

    class Meta:
        ordering = ("position", "title")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("module", "position"), name="unique_unit_position_per_module"
            )
        ]

    def __str__(self):
        return self.title


class Lesson(BaseModel):
    unit = models.ForeignKey(Unit, on_delete=models.CASCADE, related_name="lessons")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    video_url = models.URLField(blank=True)
    position = models.PositiveIntegerField()
    duration_minutes = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    objects = LessonQuerySet.as_manager()

    class Meta:
        ordering = ("position", "title")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("unit", "position"), name="unique_lesson_position_per_unit"
            )
        ]

    def __str__(self):
        return self.title


class Material(BaseModel):
    class Kind(models.TextChoices):
        LINK = "LINK", "External link"
        FILE = "FILE", "Uploaded file"

    lesson = models.ForeignKey(
        Lesson, on_delete=models.CASCADE, related_name="materials"
    )
    title = models.CharField(max_length=200)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    url = models.URLField(blank=True)
    file = models.ForeignKey(
        "files.StoredFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="materials",
    )
    is_active = models.BooleanField(default=True)

    objects = MaterialQuerySet.as_manager()

    class Meta:
        ordering = ("title",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=(
                    Q(kind="LINK", url__gt="", file__isnull=True)
                    | Q(kind="FILE", file__isnull=False, url="")
                ),
                name="material_link_or_file_required",
            )
        ]

    def __str__(self):
        return self.title
