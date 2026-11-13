from django.db import transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone
from django.utils.text import slugify
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.accounts.roles import ADMIN_ROLES, Role
from apps.assessment.models import Assessment
from apps.enrollment.models import CourseAccess, Enrollment
from apps.scheduling.models import ClassGroup
from common.audit import get_object_unit, record_audit
from common.scoping import ScopedViewSetMixin

from .models import Course, CourseAssignment, CourseModule, Lesson, Material, Unit
from .permissions import (
    AcademicsPermission,
    CourseAssignmentPermission,
    get_course,
    may_manage_course,
    may_manage_course_department,
)
from .serializers import (
    CourseAssignmentSerializer,
    CourseModuleSerializer,
    CourseSerializer,
    CourseVersionSerializer,
    CurriculumReorderSerializer,
    LessonSerializer,
    MaterialSerializer,
    UnitSerializer,
)


class AcademicViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = (AcademicsPermission,)

    def get_create_kwargs(self, serializer):
        return {}

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save(**self.get_create_kwargs(serializer))
            record_audit(
                actor=self.request.user,
                action="created",
                obj=instance,
                unit=get_object_unit(instance),
                after=self.get_serializer(instance=instance).data,
            )

    def perform_update(self, serializer):
        instance = serializer.instance
        if isinstance(instance, Course):
            expected_version = serializer.validated_data.get("version")
            if expected_version is None:
                raise ValidationError({"version": "Current version is required."})
            with transaction.atomic():
                course = Course.objects.select_for_update().get(pk=instance.pk)
                if expected_version != course.version:
                    raise ValidationError(
                        {
                            "version": "Someone else edited this course. Refresh and try again."
                        }
                    )
                self._assert_course_mutable(course)
                department = serializer.validated_data.get(
                    "department", course.department
                )
                department_changed = department.pk != course.department_id
                if department_changed:
                    if department.unit_id != course.unit_id:
                        raise ValidationError(
                            {
                                "department": (
                                    "A course cannot be moved to another business unit."
                                )
                            }
                        )
                    user = self.request.user
                    if not (
                        user.has_role_global(*ADMIN_ROLES)
                        or user.has_role_for_unit(Role.UNIT_MANAGER, course.unit_id)
                    ):
                        raise PermissionDenied(
                            "Only this unit's manager or an administrator may move a course."
                        )
                    blockers = []
                    if ClassGroup.objects.filter(course=course).exists():
                        blockers.append("classes")
                    if Enrollment.objects.filter(course=course).exists():
                        blockers.append("enrollments")
                    if CourseAccess.objects.filter(course=course).exists():
                        blockers.append("course access rows")
                    if (
                        Assessment.objects.filter(template__course=course)
                        .filter(
                            Q(submissions__isnull=False)
                            | Q(grades__isnull=False)
                        )
                        .exists()
                    ):
                        blockers.append("assessments with submissions or grades")
                    if blockers:
                        raise ValidationError(
                            {
                                "department": (
                                    "The course department cannot change while it has "
                                    f"{', '.join(blockers)}."
                                )
                            }
                        )
                if course.class_groups.exists():
                    locked_fields = {
                        "program": (
                            course.program_id,
                            getattr(
                                serializer.validated_data.get(
                                    "program", course.program
                                ),
                                "pk",
                                None,
                            ),
                        ),
                        "code": (
                            course.code,
                            serializer.validated_data.get("code", course.code),
                        ),
                        "slug": (
                            course.slug,
                            serializer.validated_data.get("slug", course.slug),
                        ),
                    }
                    errors = {
                        field: "This field cannot be changed after classes exist."
                        for field, (current, incoming) in locked_fields.items()
                        if current != incoming
                    }
                    if errors:
                        raise ValidationError(errors)
                before = self.get_serializer(instance=course).data
                serializer.instance = course
                serializer.validated_data.pop("version", None)
                instance = serializer.save()
                instance.version = course.version + 1
                instance.save(update_fields=("version", "updated_at"))
                after = self.get_serializer(instance=instance).data
                record_audit(
                    actor=self.request.user,
                    action=(
                        "course_department_moved" if department_changed else "updated"
                    ),
                    obj=instance,
                    unit=course.unit,
                    before=before,
                    after=after,
                )
            return
        elif isinstance(instance, CourseModule):
            course = serializer.validated_data.get("course", instance.course)
        elif isinstance(instance, Unit):
            module = serializer.validated_data.get("module", instance.module)
            course = module.course
        elif isinstance(instance, Lesson):
            unit = serializer.validated_data.get("unit", instance.unit)
            course = unit.module.course
        else:
            lesson = serializer.validated_data.get("lesson", instance.lesson)
            course = lesson.unit.module.course
        if not may_manage_course(self.request.user, course):
            raise PermissionDenied("You may not edit this course.")
        before = self.get_serializer(instance=serializer.instance).data
        with transaction.atomic():
            instance = serializer.save()
            if isinstance(instance, Course):
                instance.version += 1
                instance.save(update_fields=("version", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="updated",
                obj=instance,
                unit=get_object_unit(instance),
                before=before,
                after=self.get_serializer(instance=instance).data,
            )

    def perform_destroy(self, instance):
        before = self.get_serializer(instance=instance).data
        with transaction.atomic():
            instance.is_active = False
            instance.save(update_fields=("is_active", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="archived",
                obj=instance,
                unit=get_object_unit(instance),
                before=before,
                after=self.get_serializer(instance=instance).data,
            )


class CourseAssignmentViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = CourseAssignment.objects.select_related(
        "unit", "course", "teacher"
    ).all()
    serializer_class = CourseAssignmentSerializer
    permission_classes = (CourseAssignmentPermission,)
    http_method_names = ("get", "post", "delete", "head", "options")
    filterset_fields = ("course", "teacher", "is_active")
    search_fields = ("course__title", "teacher__display_name", "teacher__email")
    ordering_fields = ("created_at", "teacher__display_name")

    def perform_create(self, serializer):
        data = serializer.validated_data
        with transaction.atomic():
            assignment, created = CourseAssignment.objects.get_or_create(
                course=data["course"],
                teacher=data["teacher"],
                defaults={
                    "unit": data["course"].unit,
                    "can_edit_content": data["can_edit_content"],
                },
            )
            before = None
            if not created:
                before = self.get_serializer(assignment).data
                assignment.can_edit_content = data["can_edit_content"]
                assignment.is_active = True
                assignment.save(
                    update_fields=("can_edit_content", "is_active", "updated_at")
                )
            action = "created" if created else "reactivated"
            record_audit(
                actor=self.request.user,
                action=f"course_teacher_{action}",
                obj=assignment,
                unit=assignment.unit,
                before=before,
                after=self.get_serializer(assignment).data,
            )
        serializer.instance = assignment

    def perform_destroy(self, instance):
        before = self.get_serializer(instance).data
        with transaction.atomic():
            instance.is_active = False
            instance.save(update_fields=("is_active", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="course_teacher_unassigned",
                obj=instance,
                unit=instance.unit,
                before=before,
                after=self.get_serializer(instance).data,
            )


class CourseViewSet(AcademicViewSet):
    queryset = (
        Course.objects.annotate(
            has_classes=Exists(ClassGroup.objects.filter(course_id=OuterRef("pk")))
        )
        .select_related("department", "program", "created_by", "cover_image")
        .all()
    )
    serializer_class = CourseSerializer
    lookup_field = "slug"
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    search_fields = ("title", "code", "summary", "department__name")
    ordering_fields = ("title", "code", "created_at")
    filterset_fields = ("department", "program", "status", "is_active")

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        department = serializer.validated_data["department"]
        if not may_manage_course_department(self.request.user, department):
            raise PermissionDenied("You may not manage courses in this department.")
        super().perform_create(serializer)

    def get_create_kwargs(self, serializer):
        return {"created_by": self.request.user}

    def _assert_course_mutable(self, course):
        if not may_manage_course(self.request.user, course):
            raise PermissionDenied("You may not edit this course.")
        if not course.is_active:
            raise ValidationError({"detail": "Archived courses cannot be changed."})

    def _course_action_version(self, request):
        serializer = CourseVersionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data["version"]

    def _lock_course_for_action(self, course_id, expected_version):
        course = Course.objects.select_for_update().get(pk=course_id)
        if expected_version != course.version:
            raise ValidationError(
                {"version": "Someone else edited this course. Refresh and try again."}
            )
        self._assert_course_mutable(course)
        return course

    def _course_duplicate(self, course):
        title = f"{course.title} (Copy)"
        duplicate = Course.objects.create(
            unit=course.unit,
            department=course.department,
            program=course.program,
            cover_image=course.cover_image,
            created_by=self.request.user,
            title=title,
            slug=self._ensure_unique_slug(title),
            code=self._ensure_unique_code(course.code),
            summary=course.summary,
            description=course.description,
            learning_outcomes=list(course.learning_outcomes or []),
            status=Course.Status.DRAFT,
            is_active=True,
        )
        for module in course.modules.all():
            new_module = duplicate.modules.create(
                title=module.title,
                description=module.description,
                position=module.position,
                is_active=module.is_active,
            )
            for unit in module.units.all():
                new_unit = new_module.units.create(
                    title=unit.title,
                    description=unit.description,
                    position=unit.position,
                    is_active=unit.is_active,
                )
                for lesson in unit.lessons.all():
                    new_lesson = new_unit.lessons.create(
                        title=lesson.title,
                        description=lesson.description,
                        video_url=lesson.video_url,
                        position=lesson.position,
                        duration_minutes=lesson.duration_minutes,
                        is_active=lesson.is_active,
                    )
                    for material in lesson.materials.all():
                        new_lesson.materials.create(
                            title=material.title,
                            kind=material.kind,
                            url=material.url,
                            file=material.file,
                            is_active=material.is_active,
                        )
        return duplicate

    @staticmethod
    def _ensure_unique_slug(value):
        slug = slugify(value)
        base = slug
        index = 1
        while Course.objects.filter(slug=slug).exists():
            slug = f"{base}-{index}"
            index += 1
        return slug

    @staticmethod
    def _ensure_unique_code(value):
        base = f"{value}-COPY"
        index = 1
        while True:
            suffix = "" if index == 1 else f"-{index}"
            code = f"{base[: 40 - len(suffix)]}{suffix}"
            if not Course.objects.filter(code=code).exists():
                return code
            index += 1

    @extend_schema(request=CourseVersionSerializer)
    @action(detail=True, methods=("post",))
    def publish(self, request, slug=None):
        source = self.get_object()
        expected_version = self._course_action_version(request)
        with transaction.atomic():
            course = self._lock_course_for_action(source.pk, expected_version)
            if course.status == Course.Status.PUBLISHED:
                return Response(self.get_serializer(course).data)
            if course.status != Course.Status.DRAFT:
                raise ValidationError(
                    {"status": "Only draft courses can be published."}
                )
            before = {"status": course.status, "version": course.version}
            course.status = Course.Status.PUBLISHED
            course.version += 1
            course.save(update_fields=("status", "version", "updated_at"))
            record_audit(
                actor=request.user,
                action="course_published",
                obj=course,
                unit=course.unit,
                before=before,
                after={"status": course.status, "version": course.version},
            )
        return Response(self.get_serializer(course).data)

    @extend_schema(request=CourseVersionSerializer)
    @action(detail=True, methods=("post",))
    def unpublish(self, request, slug=None):
        source = self.get_object()
        expected_version = self._course_action_version(request)
        with transaction.atomic():
            course = self._lock_course_for_action(source.pk, expected_version)
            if course.status != Course.Status.PUBLISHED:
                raise ValidationError(
                    {"status": "Only published courses can be unpublished."}
                )
            before = {"status": course.status, "version": course.version}
            course.status = Course.Status.DRAFT
            course.version += 1
            course.save(update_fields=("status", "version", "updated_at"))
            record_audit(
                actor=request.user,
                action="course_unpublished",
                obj=course,
                unit=course.unit,
                before=before,
                after={"status": course.status, "version": course.version},
            )
        return Response(self.get_serializer(course).data)

    @extend_schema(request=CourseVersionSerializer)
    @action(detail=True, methods=("post",))
    def archive(self, request, slug=None):
        source = self.get_object()
        expected_version = self._course_action_version(request)
        with transaction.atomic():
            course = self._lock_course_for_action(source.pk, expected_version)
            before = {"is_active": course.is_active, "version": course.version}
            course.is_active = False
            course.version += 1
            course.save(update_fields=("is_active", "version", "updated_at"))
            record_audit(
                actor=request.user,
                action="course_archived",
                obj=course,
                unit=course.unit,
                before=before,
                after={"is_active": course.is_active, "version": course.version},
            )
        return Response(self.get_serializer(course).data)

    @extend_schema(request=CourseVersionSerializer)
    @action(detail=True, methods=("post",))
    def duplicate(self, request, slug=None):
        source = self.get_object()
        expected_version = self._course_action_version(request)
        with transaction.atomic():
            course = self._lock_course_for_action(source.pk, expected_version)
            duplicate = self._course_duplicate(course)
            record_audit(
                actor=request.user,
                action="course_duplicated",
                obj=duplicate,
                unit=duplicate.unit,
                before={"source_id": str(course.id)},
                after={"id": str(duplicate.id), "status": duplicate.status},
            )
        return Response(self.get_serializer(duplicate).data)


class CurriculumReorderViewSet(AcademicViewSet):
    parent_model = None
    parent_field = ""

    @extend_schema(request=CurriculumReorderSerializer)
    @action(detail=False, methods=("post",), url_path="reorder")
    def reorder(self, request):
        serializer = CurriculumReorderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent_id = serializer.validated_data["parent_id"]
        try:
            with transaction.atomic():
                parent = self.parent_model.objects.select_for_update().get(pk=parent_id)
                course = get_course(parent)
                if not course or not may_manage_course(request.user, course):
                    raise PermissionDenied("You may not edit this course.")
                items = list(
                    self.queryset.model.objects.select_for_update()
                    .filter(**{f"{self.parent_field}_id": parent_id})
                    .order_by("position", "pk")
                )
                item_by_id = {item.pk: item for item in items}
                ordered_ids = serializer.validated_data["ids"]
                if set(ordered_ids) != set(item_by_id):
                    raise ValidationError(
                        {
                            "ids": (
                                "Include every item belonging to the selected parent "
                                "exactly once."
                            )
                        }
                    )

                before_positions = {item.pk: item.position for item in items}
                now = timezone.now()
                temporary_position = max((item.position for item in items), default=0)
                for offset, item_id in enumerate(ordered_ids, start=1):
                    item = item_by_id[item_id]
                    item.position = temporary_position + offset
                    item.updated_at = now
                if items:
                    self.queryset.model.objects.bulk_update(
                        items, ("position", "updated_at")
                    )

                for position, item_id in enumerate(ordered_ids, start=1):
                    item = item_by_id[item_id]
                    item.position = position
                    item.updated_at = now
                if items:
                    self.queryset.model.objects.bulk_update(
                        items, ("position", "updated_at")
                    )
                for item_id in ordered_ids:
                    item = item_by_id[item_id]
                    if before_positions[item_id] != item.position:
                        record_audit(
                            actor=request.user,
                            action="reordered",
                            obj=item,
                            unit=get_object_unit(item),
                            before={"position": before_positions[item_id]},
                            after={"position": item.position},
                        )
                items.sort(key=lambda item: (item.position, str(item.pk)))
                return Response(self.get_serializer(items, many=True).data)
        except self.parent_model.DoesNotExist as exc:
            raise ValidationError(
                {"parent_id": "The selected parent does not exist."}
            ) from exc


class CourseModuleViewSet(CurriculumReorderViewSet):
    teacher_content_management = True
    queryset = CourseModule.objects.select_related("course").all()
    serializer_class = CourseModuleSerializer
    parent_model = Course
    parent_field = "course"
    search_fields = ("title", "description")
    ordering_fields = ("position", "title")
    filterset_fields = ("course", "is_active")

    def perform_create(self, serializer):
        course = serializer.validated_data["course"]
        if not may_manage_course(self.request.user, course):
            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)


class UnitViewSet(CurriculumReorderViewSet):
    teacher_content_management = True
    queryset = Unit.objects.select_related("module__course").all()
    serializer_class = UnitSerializer
    parent_model = CourseModule
    parent_field = "module"
    search_fields = ("title", "description")
    ordering_fields = ("position", "title")
    filterset_fields = ("module", "is_active")

    def perform_create(self, serializer):
        if not may_manage_course(
            self.request.user, serializer.validated_data["module"].course
        ):
            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)


class LessonViewSet(CurriculumReorderViewSet):
    teacher_content_management = True
    queryset = Lesson.objects.select_related("unit__module__course").all()
    serializer_class = LessonSerializer
    parent_model = Unit
    parent_field = "unit"
    search_fields = ("title", "description")
    ordering_fields = ("position", "title")
    filterset_fields = ("unit", "is_active")

    def perform_create(self, serializer):
        course = serializer.validated_data["unit"].module.course
        if not may_manage_course(self.request.user, course):
            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)


class MaterialViewSet(AcademicViewSet):
    teacher_content_management = True
    queryset = Material.objects.select_related(
        "lesson__unit__module__course", "file"
    ).all()
    serializer_class = MaterialSerializer
    search_fields = ("title",)
    ordering_fields = ("title", "created_at")
    filterset_fields = ("lesson", "kind")

    def perform_create(self, serializer):
        course = serializer.validated_data["lesson"].unit.module.course
        if not may_manage_course(self.request.user, course):
            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)
