from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.org.models import BusinessUnit

from .models import RoleAssignment, User


class BusinessUnitSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessUnit
        fields = ("id", "code", "name")
        read_only_fields = fields


class RoleAssignmentSerializer(serializers.ModelSerializer):
    unit = BusinessUnitSummarySerializer(read_only=True, allow_null=True)

    class Meta:
        model = RoleAssignment
        fields = ("role", "unit")
        read_only_fields = fields


class MeSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    assignments = serializers.SerializerMethodField()
    is_global_read = serializers.SerializerMethodField()
    awaiting_approval = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "display_name",
            "phone_number",
            "role",
            "assignments",
            "is_global_read",
            "awaiting_approval",
            "is_active",
        )
        read_only_fields = fields

    def get_role(self, obj) -> str | None:
        return obj.role

    @extend_schema_field(RoleAssignmentSerializer(many=True))
    def get_assignments(self, obj):
        assignments = obj.assignments.filter(is_active=True).select_related("unit")
        return RoleAssignmentSerializer(assignments, many=True).data

    def get_is_global_read(self, obj) -> bool:
        return obj.has_global_read()

    def get_awaiting_approval(self, obj) -> bool:
        return not obj.roles()


class MeUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ("display_name", "phone_number")

    def validate(self, attrs):
        unknown_fields = set(self.initial_data) - set(self.fields)
        if unknown_fields:
            raise serializers.ValidationError(
                {field: "This field is not editable." for field in unknown_fields}
            )
        return attrs


class ReportsOverviewSerializer(serializers.Serializer):
    departments = serializers.IntegerField(required=False)
    programs = serializers.IntegerField(required=False)
    courses = serializers.IntegerField(required=False)
    students = serializers.IntegerField(required=False)
    pending_applications = serializers.IntegerField(required=False)
    pending_enrollments = serializers.IntegerField(required=False)
    users = serializers.IntegerField(required=False)
    staff = serializers.IntegerField(required=False)
    assessments = serializers.IntegerField(required=False)
    submissions_to_grade = serializers.IntegerField(required=False)
