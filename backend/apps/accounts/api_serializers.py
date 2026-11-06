from uuid import UUID

from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.org.models import BusinessUnit, Department

from .roles import UNIT_SCOPED_ROLES, Role

User = get_user_model()
ASSIGNABLE_ROLE_CHOICES = tuple(
    (role.value, role.label) for role in Role if role != Role.STUDENT
)


def validate_department_assignments(attrs):
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
    unit_id = attrs.get("unit_id")
    if role in UNIT_SCOPED_ROLES and unit_id is None:
        raise serializers.ValidationError(
            {"unit_id": "A business unit is required for this role."}
        )
    if unit_id is not None and (
        role not in UNIT_SCOPED_ROLES | {Role.BURSAR}
        or not BusinessUnit.objects.filter(id=unit_id, is_active=True).exists()
    ):
        raise serializers.ValidationError(
            {"unit_id": "Select an active unit valid for this role."}
        )
    return attrs


class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    department_ids = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "email",
            "display_name",
            "role",
            "is_active",
            "department_ids",
            "created_at",
        )
        read_only_fields = fields

    def get_department_ids(self, obj) -> list[UUID]:
        return sorted((scope.department_id for scope in obj.role_scopes.all()), key=str)

    def get_role(self, obj) -> str | None:
        return obj.role


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


class ChangeRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=ASSIGNABLE_ROLE_CHOICES, allow_null=True)
    unit_id = serializers.UUIDField(required=False)
    department_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )

    def validate(self, attrs):
        return validate_department_assignments(attrs)
