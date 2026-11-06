from django.db import transaction
from rest_framework import viewsets
from rest_framework.permissions import AllowAny

from apps.accounts.roles import Role
from common.audit import get_object_unit, record_audit
from common.scoping import ScopedViewSetMixin

from .models import Course, CourseModule, Lesson, Material, Unit
from .permissions import AcademicsPermission, may_manage_course
from .serializers import (
    CourseModuleSerializer,
    CourseSerializer,
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
            course = instance
            department = serializer.validated_data.get("department", course.department)
            if (
                self.request.user.role == Role.HOD
                and not department.role_scopes.filter(user=self.request.user).exists()
            ):
                from rest_framework.exceptions import PermissionDenied

                raise PermissionDenied(
                    "You may only manage courses in your departments."
                )
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
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may not edit this course.")
        before = self.get_serializer(instance=serializer.instance).data
        with transaction.atomic():
            instance = serializer.save()
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


class CourseViewSet(AcademicViewSet):
    queryset = Course.objects.select_related(
        "department", "program", "created_by", "cover_image"
    ).all()
    serializer_class = CourseSerializer
    lookup_field = "slug"
    search_fields = ("title", "code", "summary", "department__name")
    ordering_fields = ("title", "code", "created_at")
    filterset_fields = ("department", "program", "status", "is_active")

    def get_permissions(self):
        if self.action in {"list", "retrieve"}:
            return [AllowAny()]
        return super().get_permissions()

    def perform_create(self, serializer):
        department = serializer.validated_data["department"]
        if (
            self.request.user.role == Role.HOD
            and not department.role_scopes.filter(user=self.request.user).exists()
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only create courses in your departments.")
        super().perform_create(serializer)

    def get_create_kwargs(self, serializer):
        return {"created_by": self.request.user}


class CourseModuleViewSet(AcademicViewSet):
    teacher_content_management = True
    queryset = CourseModule.objects.select_related("course").all()
    serializer_class = CourseModuleSerializer
    search_fields = ("title", "description")
    ordering_fields = ("position", "title")
    filterset_fields = ("course", "is_active")

    def perform_create(self, serializer):
        course = serializer.validated_data["course"]
        if not may_manage_course(self.request.user, course):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)


class UnitViewSet(AcademicViewSet):
    teacher_content_management = True
    queryset = Unit.objects.select_related("module__course").all()
    serializer_class = UnitSerializer
    search_fields = ("title", "description")
    ordering_fields = ("position", "title")
    filterset_fields = ("module", "is_active")

    def perform_create(self, serializer):
        if not may_manage_course(
            self.request.user, serializer.validated_data["module"].course
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)


class LessonViewSet(AcademicViewSet):
    teacher_content_management = True
    queryset = Lesson.objects.select_related("unit__module__course").all()
    serializer_class = LessonSerializer
    search_fields = ("title", "description")
    ordering_fields = ("position", "title")
    filterset_fields = ("unit", "is_active")

    def perform_create(self, serializer):
        course = serializer.validated_data["unit"].module.course
        if not may_manage_course(self.request.user, course):
            from rest_framework.exceptions import PermissionDenied

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
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may not edit this course.")
        super().perform_create(serializer)
