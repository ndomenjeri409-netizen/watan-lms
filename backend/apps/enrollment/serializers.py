from rest_framework import serializers

from apps.academics.models import Course
from apps.org.models import Program
from apps.people.serializers import StudentSerializer

from .models import Application, CourseAccess, Enrollment


class ApplicationSerializer(serializers.ModelSerializer):
    student_profile = StudentSerializer(source="student", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    course_code = serializers.CharField(source="course.code", read_only=True)
    department = serializers.PrimaryKeyRelatedField(read_only=True)

    class Meta:
        model = Application
        fields = (
            "id",
            "department",
            "program",
            "course",
            "course_title",
            "course_code",
            "first_name",
            "last_name",
            "email",
            "phone",
            "statement",
            "status",
            "student",
            "student_profile",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
        )
        read_only_fields = (
            "id",
            "status",
            "student",
            "student_profile",
            "reviewed_by",
            "reviewed_at",
            "review_note",
            "created_at",
        )

    def validate(self, attrs):
        course = attrs["course"]
        program = attrs.get("program")
        if course.status != Course.Status.PUBLISHED or not course.is_active:
            raise serializers.ValidationError(
                {"course": "Applications are only accepted for published courses."}
            )
        if program and program.department_id != course.department_id:
            raise serializers.ValidationError(
                {
                    "program": "The selected program does not match the course department."
                }
            )
        if (
            program
            and not Program.objects.filter(pk=program.pk, is_active=True).exists()
        ):
            raise serializers.ValidationError({"program": "Select an active program."})
        attrs["department"] = course.department
        return attrs


class EnrollmentSerializer(serializers.ModelSerializer):
    student_profile = StudentSerializer(source="student", read_only=True)
    course_title = serializers.CharField(source="course.title", read_only=True)
    course_code = serializers.CharField(source="course.code", read_only=True)

    class Meta:
        model = Enrollment
        fields = (
            "id",
            "unit",
            "student",
            "student_profile",
            "course",
            "course_title",
            "course_code",
            "class_group",
            "application",
            "status",
            "approved_by",
            "activated_at",
            "created_at",
        )
        read_only_fields = fields


class CourseAccessSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    course_slug = serializers.CharField(source="course.slug", read_only=True)

    class Meta:
        model = CourseAccess
        fields = ("id", "course", "course_title", "course_slug", "is_active")
        read_only_fields = fields


class StudentProvisioningSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    registration_number = serializers.CharField()
    email = serializers.EmailField(allow_blank=True)


class ApproveApplicationResponseSerializer(serializers.Serializer):
    application = ApplicationSerializer()
    student = StudentProvisioningSummarySerializer()
    enrollment_id = serializers.UUIDField()


class RejectApplicationSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class TransitionEnrollmentSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Enrollment.Status.choices)
    class_group = serializers.UUIDField(required=False)
