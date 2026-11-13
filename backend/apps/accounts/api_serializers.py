from uuid import UUID

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.org.models import BusinessUnit, Department

from .models import RoleAssignment
from .roles import UNIT_SCOPED_ROLES, Role
from .serializers import BusinessUnitSummarySerializer

User = get_user_model()
ASSIGNABLE_ROLE_CHOICES = tuple(
    (role.value, role.label) for role in Role if role != Role.STUDENT
)


def validate_department_assignments(attrs, *, unit_key="unit_id"):
    department_ids = attrs.get("department_ids", [])
    role = attrs.get("role")
    if role == Role.HOD and not department_ids:
        raise serializers.ValidationError(
            {"department_ids": "Assign at least one department to an HOD."}
        )
    if role != Role.HOD and department_ids:
        raise serializers.ValidationError(
            {"department_ids": "Only HOD users can have department scopes."}
        )
    if len(department_ids) != len(set(department_ids)):
        raise serializers.ValidationError(
            {"department_ids": "Department assignments must not contain duplicates."}
        )
    if Department.objects.filter(id__in=department_ids).count() != len(department_ids):
        raise serializers.ValidationError(
            {"department_ids": "One or more departments do not exist."}
        )
    unit_id = attrs.get(unit_key)
    if role in UNIT_SCOPED_ROLES and unit_id is None:
        raise serializers.ValidationError(
            {unit_key: "A business unit is required for this role."}
        )
    if (
        role in Role.values
        and role
        in {
            Role.SUPER_ADMIN,
            Role.ADMIN,
            Role.DIRECTOR,
            Role.AUDITOR,
        }
        and unit_id is not None
    ):
        raise serializers.ValidationError(
            {unit_key: "Group roles cannot be assigned to a business unit."}
        )
    if unit_id is not None:
        unit = (
            unit_id
            if isinstance(unit_id, BusinessUnit)
            else BusinessUnit.objects.filter(id=unit_id, is_active=True).first()
        )
        if (
            role not in UNIT_SCOPED_ROLES | {Role.BURSAR}
            or unit is None
            or not unit.is_active
        ):
            raise serializers.ValidationError(
                {unit_key: "Select an active unit valid for this role."}
            )
        if (
            department_ids
            and Department.objects.filter(id__in=department_ids)
            .exclude(unit_id=unit.pk)
            .exists()
        ):
            raise serializers.ValidationError(
                {"department_ids": "Departments must belong to the selected unit."}
            )
    return attrs


class UserAssignmentSerializer(serializers.ModelSerializer):
    unit = BusinessUnitSummarySerializer(read_only=True, allow_null=True)

    class Meta:
        model = RoleAssignment
        fields = ("id", "role", "unit", "is_active")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    department_ids = serializers.SerializerMethodField()
    assignments = UserAssignmentSerializer(many=True, read_only=True)
    status = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "display_name",
            "role",
            "is_active",
            "department_ids",
            "assignments",
            "status",
            "created_at",
        )
        read_only_fields = fields

    def get_department_ids(self, obj) -> list[UUID]:
        return sorted((scope.department_id for scope in obj.role_scopes.all()), key=str)

    def get_role(self, obj) -> str | None:
        return obj.role

    def get_status(self, obj) -> str:
        return (
            "ACTIVE"
            if any(assignment.is_active for assignment in obj.assignments.all())
            else "PENDING"
        )


class InviteUserSerializer(serializers.Serializer):
    email = serializers.EmailField()
    display_name = serializers.CharField(max_length=200, allow_blank=True)
    role = serializers.ChoiceField(choices=ASSIGNABLE_ROLE_CHOICES)
    unit_id = serializers.UUIDField(required=False)
    department_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )

    def validate(self, attrs):
        return validate_department_assignments(attrs)


class RoleAssignmentCreateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ASSIGNABLE_ROLE_CHOICES)
    unit = serializers.PrimaryKeyRelatedField(
        queryset=BusinessUnit.objects.filter(is_active=True), required=False
    )
    department_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )

    def validate(self, attrs):
        return validate_department_assignments(attrs, unit_key="unit")
