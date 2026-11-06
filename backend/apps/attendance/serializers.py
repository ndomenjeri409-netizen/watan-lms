from rest_framework import serializers

from .models import AttendanceRecord, AttendanceSession


class AttendanceSessionSerializer(serializers.ModelSerializer):
    class_group_name = serializers.CharField(source="class_group.name", read_only=True)
    course_title = serializers.CharField(
        source="class_group.course.title", read_only=True
    )
    record_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AttendanceSession
        fields = (
            "id",
            "class_group",
            "class_group_name",
            "course_title",
            "opened_by",
            "title",
            "is_open",
            "opened_at",
            "closed_at",
            "record_count",
        )
        read_only_fields = ("id", "opened_by", "is_open", "opened_at", "closed_at")


class OpenSessionSerializer(serializers.Serializer):
    class_group = serializers.UUIDField()
    title = serializers.CharField(max_length=160, allow_blank=True, required=False)


class QrIssueSerializer(serializers.Serializer):
    token = serializers.CharField()
    expires_at = serializers.DateTimeField()
    check_in_url = serializers.URLField()


class CheckInSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=256)
    client_checkin_id = serializers.UUIDField(required=False)


class AttendanceRecordSerializer(serializers.ModelSerializer):
    registration_number = serializers.CharField(
        source="student.registration_number", read_only=True
    )
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = AttendanceRecord
        fields = (
            "id",
            "session",
            "student",
            "registration_number",
            "student_name",
            "status",
            "checked_in_at",
        )
        read_only_fields = fields

    def get_student_name(self, obj) -> str:
        return f"{obj.student.first_name} {obj.student.last_name}"
