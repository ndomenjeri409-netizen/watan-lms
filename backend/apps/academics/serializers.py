from rest_framework import serializers

from apps.files.models import StoredFile

from .models import Course, CourseModule, Lesson, Material, Unit


class CourseSerializer(serializers.ModelSerializer):
    slug = serializers.SlugField(required=False)

    class Meta:
        model = Course
        fields = (
            "id",
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
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_by", "created_at", "updated_at")

    def validate(self, attrs):
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
        return attrs


class CourseModuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = CourseModule
        fields = ("id", "course", "title", "description", "position", "is_active")
        read_only_fields = ("id",)


class UnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = Unit
        fields = ("id", "module", "title", "description", "position", "is_active")
        read_only_fields = ("id",)


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
        )
        read_only_fields = ("id",)


class MaterialSerializer(serializers.ModelSerializer):
    class Meta:
        model = Material
        fields = ("id", "lesson", "title", "kind", "url", "file", "is_active")
        read_only_fields = ("id",)

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
