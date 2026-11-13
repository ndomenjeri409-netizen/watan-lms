from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils.text import slugify

from apps.accounts.roles import ADMIN_ROLES, Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet, UnitScopedQuerySet


class CourseQuerySet(UnitScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.filter(status=Course.Status.PUBLISHED, is_active=True)
        if user.has_global_read():
            return self

        scope = Q(pk__in=[])
        public_courses = Q(status=Course.Status.PUBLISHED, is_active=True)

        if user.has_role(Role.STUDENT):
            scope |= (
                Q(
                    department__students__user=user,
                )
                & public_courses
            )

        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(department_id__in=department_ids)

        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(unit_id__in=manager_unit_ids)

        teacher_unit_ids = user.unit_ids_for(Role.TEACHER)
        if teacher_unit_ids:
            scope |= Q(unit_id__in=teacher_unit_ids) & (
                Q(
                    teacher_assignments__teacher=user,
                    teacher_assignments__is_active=True,
                )
                | public_courses
            )

        support_unit_ids = user.unit_ids_for(Role.BURSAR, Role.CASHIER)
        if support_unit_ids:
            scope |= Q(unit_id__in=support_unit_ids) & public_courses

        return self.filter(scope).distinct()


class Course(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"

    version = models.PositiveIntegerField(default=1)

    unit = models.ForeignKey(
        "org.BusinessUnit", on_delete=models.PROTECT, related_name="courses"
    )
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
        derived_unit = self.unit_id is None
        if derived_unit and self.department_id:
            self.unit_id = self.department.unit_id
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(set(kwargs["update_fields"]) | {"unit"})
        self.clean()
        super().save(*args, **kwargs)

    def bump_version(self):
        self.version += 1
        self.save(update_fields=("version", "updated_at"))

    def clean(self):
        errors = {}
        if (
            self.department_id
            and self.unit_id
            and self.department.unit_id != self.unit_id
        ):
            errors["unit"] = "The course must use its department's unit."
        if (
            self.program_id
            and self.department_id
            and self.program.department_id != self.department_id
        ):
            errors["program"] = "The selected program belongs to another department."
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class CourseAssignmentQuerySet(UnitScopedQuerySet):
    unit_field = "unit"

    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_global_read():
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(course__department_id__in=department_ids)

        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(unit_id__in=manager_unit_ids)

        if user.has_role(Role.TEACHER):
            scope |= Q(teacher=user, is_active=True)

        return self.filter(scope).distinct()


class CourseAssignment(BaseModel):
    unit = models.ForeignKey(
        "org.BusinessUnit",
        on_delete=models.PROTECT,
        related_name="course_assignments",
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name="teacher_assignments"
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="course_assignments",
    )
    can_edit_content = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    objects = CourseAssignmentQuerySet.as_manager()

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("course", "teacher"),
                name="unique_course_teacher_assignment",
            )
        ]

    def clean(self):
        if self.course_id and self.unit_id and self.course.unit_id != self.unit_id:
            raise ValidationError(
                {"unit": "The assignment must use the course's unit."}
            )

    def save(self, *args, **kwargs):
        if self.unit_id is None and self.course_id:
            self.unit_id = self.course.unit_id
            if kwargs.get("update_fields") is not None:
                kwargs["update_fields"] = tuple(set(kwargs["update_fields"]) | {"unit"})
        self.clean()
        super().save(*args, **kwargs)


class CourseChildQuerySet(ScopedQuerySet):
    course_path = "course"
    visibility_parents = ()

    def for_user(self, user):
        queryset = self.filter(
            **{f"{self.course_path}__in": Course.objects.for_user(user).values("id")}
        )
        visible_fields = {"is_active": True, "is_visible": True}
        for parent_path in self.visibility_parents:
            visible_fields[f"{parent_path}__is_active"] = True
            visible_fields[f"{parent_path}__is_visible"] = True
        if user.is_authenticated and user.has_role_global(*ADMIN_ROLES):
            return queryset
        if not user.is_authenticated:
            return queryset.filter(**visible_fields)
        department_ids = user.department_ids_for_hod()
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        teacher_unit_ids = user.unit_ids_for(Role.TEACHER)
        elevated_courses = Course.objects.filter(
            Q(department_id__in=department_ids)
            | Q(unit_id__in=manager_unit_ids)
            | Q(
                unit_id__in=teacher_unit_ids,
                teacher_assignments__teacher=user,
                teacher_assignments__is_active=True,
            )
        ).values("id")
        return queryset.filter(
            Q(**visible_fields) | Q(**{f"{self.course_path}__in": elevated_courses})
        )


class UnitQuerySet(CourseChildQuerySet):
    course_path = "module__course"
    visibility_parents = ("module",)


class LessonQuerySet(CourseChildQuerySet):
    course_path = "unit__module__course"
    visibility_parents = ("unit", "unit__module")


class MaterialQuerySet(CourseChildQuerySet):
    course_path = "lesson__unit__module__course"
    visibility_parents = ("lesson", "lesson__unit", "lesson__unit__module")


class CourseModule(BaseModel):
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="modules")
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    position = models.PositiveIntegerField()
    is_active = models.BooleanField(default=True)
    is_visible = models.BooleanField(default=True)

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
    is_visible = models.BooleanField(default=True)

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
    is_visible = models.BooleanField(default=True)

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
    is_visible = models.BooleanField(default=True)

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
