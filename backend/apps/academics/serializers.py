from urllib.parse import urlsplit

from django.conf import settings
from rest_framework import serializers

from apps.accounts.models import RoleAssignment
from apps.accounts.roles import Role
from apps.files.models import StoredFile

from .models import Course, CourseAssignment, CourseModule, Lesson, Material, Unit
from .permissions import may_manage_course_department


class CourseVersionSerializer(serializers.Serializer):
    version = serializers.IntegerField(min_value=1)


class CurriculumReorderSerializer(serializers.Serializer):
    parent_id = serializers.UUIDField()
    ids = serializers.ListField(child=serializers.UUIDField(), allow_empty=True)

    def validate_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Each curriculum item may appear once.")
        return value


class CourseSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False)
    version = serializers.IntegerField(required=False, min_value=1)
    has_classes = serializers.SerializerMethodField()

    class Meta:
        model = Course
        fields = (
            "id",
            "unit",
            "department",
            "program",
            "created_by",
            "title",
            "slug",
            "code",
            "summary",
            "description",
            "learning_outcomes",
            "cover_image",
            "status",
            "is_active",
            "version",
            "has_classes",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "unit",
            "created_by",
            "status",
            "is_active",
            "created_at",
            "updated_at",
            "has_classes",
        )

    def get_has_classes(self, obj) -> bool:
        annotated_value = getattr(obj, "has_classes", None)
        if annotated_value is not None:
            return annotated_value
        return obj.class_groups.exists()

    def validate(self, attrs):
        if self.instance is not None:
            lifecycle_fields = {"status", "is_active"} & set(self.initial_data)
            if lifecycle_fields:
                field = min(lifecycle_fields)
                raise serializers.ValidationError(
                    {field: "Use the course lifecycle action to change this field."}
                )
        department = attrs.get("department", getattr(self.instance, "department", None))
        program = attrs.get("program", getattr(self.instance, "program", None))
        if program and department and program.department_id != department.id:
            raise serializers.ValidationError(
                {"program": "The selected program belongs to another department."}
            )
        if "cover_image" in attrs:
            cover = attrs["cover_image"]
            if cover and (
                cover.status != StoredFile.Status.READY
                or cover.purpose != StoredFile.Purpose.COVER_IMAGE
                or cover.owner_user_id != self.context["request"].user.id
            ):
                raise serializers.ValidationError(
                    {"cover_image": "Select a ready cover image that you uploaded."}
                )
        if self.instance is not None and "version" in attrs:
            incoming_version = attrs["version"]
            if incoming_version != self.instance.version:
                raise serializers.ValidationError(
                    {
                        "version": "Someone else edited this course. Refresh and try again."
                    }
                )
        return attrs


class CourseAssignmentSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.display_name", read_only=True)
    teacher_email = serializers.EmailField(source="teacher.email", read_only=True)

    class Meta:
        model = CourseAssignment
        fields = (
            "id",
            "unit",
            "course",
            "teacher",
            "teacher_name",
            "teacher_email",
            "can_edit_content",
            "is_active",
        )
        read_only_fields = ("id", "unit", "teacher_name", "teacher_email", "is_active")

    def validate(self, attrs):
        request_user = self.context["request"].user
        course = attrs.get("course", getattr(self.instance, "course", None))
        teacher = attrs.get("teacher", getattr(self.instance, "teacher", None))

        if course:
            if not Course.objects.for_user(request_user).filter(pk=course.pk).exists():
                raise serializers.ValidationError(
                    {"course": "You may not assign teachers to this course."}
                )
            if not may_manage_course_department(request_user, course.department):
                raise serializers.ValidationError(
                    {"course": "You may not manage this course."}
                )

        if teacher and course:
            is_teacher_in_unit = RoleAssignment.objects.filter(
                user=teacher,
                role=Role.TEACHER,
                unit_id=course.unit_id,
                is_active=True,
            ).exists()
            if not is_teacher_in_unit:
                raise serializers.ValidationError(
                    {"teacher": "Select an active teacher assigned to this unit."}
                )
        return attrs


class CourseModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseModule
        fields = (
            "id",
            "course",
            "title",
            "description",
            "position",
            "is_active",
            "is_visible",
        )
        read_only_fields = ("id", "is_active")


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = (
            "id",
            "module",
            "title",
            "description",
            "position",
            "is_active",
            "is_visible",
        )
        read_only_fields = ("id", "is_active")


class LessonSerializer(serializers.ModelSerializer):
    class Meta:
        model = Lesson
        fields = (
            "id",
            "unit",
            "title",
            "description",
            "video_url",
            "position",
            "duration_minutes",
            "is_active",
            "is_visible",
        )
        read_only_fields = ("id", "is_active")

    def validate_video_url(self, value):
        if not value:
            return value
        try:
            parsed_url = urlsplit(value)
            host = (parsed_url.hostname or "").lower().rstrip(".")
            port = parsed_url.port
        except ValueError as exc:
            raise serializers.ValidationError(
                "Use a secure URL from an approved video host."
            ) from exc

        allowed_hosts = {
            host.lower().strip().rstrip(".")
            for host in settings.COURSE_VIDEO_ALLOWED_HOSTS
            if host.strip()
        }
        host_is_allowed = any(
            host == allowed or host.endswith(f".{allowed}") for allowed in allowed_hosts
        )
        if (
            parsed_url.scheme.lower() != "https"
            or not host_is_allowed
            or parsed_url.username is not None
            or parsed_url.password is not None
            or port not in (None, 443)
        ):
            raise serializers.ValidationError(
                "Video links must use HTTPS and an approved video host."
            )
        return value


class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = (
            "id",
            "lesson",
            "title",
            "kind",
            "url",
            "file",
            "is_active",
            "is_visible",
        )
        read_only_fields = ("id", "is_active")

    def validate(self, attrs):
        kind = attrs.get("kind", getattr(self.instance, "kind", None))
        url = attrs.get("url", getattr(self.instance, "url", ""))
        stored_file = attrs.get("file", getattr(self.instance, "file", None))
        if kind == Material.Kind.LINK and (not url or stored_file):
            raise serializers.ValidationError(
                {
                    "url": "External-link materials need a URL and cannot reference an uploaded file."
                }
            )
        if kind == Material.Kind.FILE:
            if not stored_file:
                raise serializers.ValidationError(
                    {"file": "Uploaded-file materials require a file."}
                )
            if (
                stored_file.purpose != StoredFile.Purpose.MATERIAL
                or stored_file.status != StoredFile.Status.READY
                or (
                    "file" in attrs
                    and stored_file.owner_user_id != self.context["request"].user.id
                )
            ):
                raise serializers.ValidationError(
                    {"file": "Select a ready course material that you uploaded."}
                )
            if url:
                raise serializers.ValidationError(
                    {"url": "Uploaded-file materials must not include a URL."}
                )
        return attrs
