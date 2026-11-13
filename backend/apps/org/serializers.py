from rest_framework import serializers

from apps.accounts.roles import ADMIN_ROLES, Role

from .models import AcademicPeriod, BusinessUnit, Campus, Department, Program


class BusinessUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessUnit
        fields = ("id", "code", "name", "kind", "currency", "modules", "is_active")
        read_only_fields = fields


class DepartmentUnitSerializer(serializers.ModelSerializer):
    class Meta:
        model = BusinessUnit
        fields = ("id", "code", "name")
        read_only_fields = fields


class DepartmentSerializer(serializers.ModelSerializer):
    program_count = serializers.SerializerMethodField()
    course_count = serializers.SerializerMethodField()
    unit = DepartmentUnitSerializer(read_only=True)

    class Meta:
        model = Department
        fields = (
            "id",
            "unit",
            "campus",
            "name",
            "code",
            "is_active",
            "archived_at",
            "program_count",
            "course_count",
        )
        read_only_fields = ("id",)

    def get_program_count(self, obj: Department) -> int:
        count = getattr(obj, "active_program_count", None)
        return (
            count if count is not None else obj.programs.filter(is_active=True).count()
        )

    def get_course_count(self, obj: Department) -> int:
        count = getattr(obj, "active_course_count", None)
        return (
            count if count is not None else obj.courses.filter(is_active=True).count()
        )


class CampusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campus
        fields = ("id", "name", "code", "is_active")
        read_only_fields = ("id",)


class DepartmentWriteSerializer(serializers.ModelSerializer):
    code = serializers.CharField(max_length=8)
    unit = serializers.PrimaryKeyRelatedField(
        queryset=BusinessUnit.objects.filter(is_active=True), required=True
    )

    def validate_unit(self, unit):
        user = self.context["request"].user
        if not (
            user.has_role_global(*ADMIN_ROLES)
            or user.has_role_for_unit(Role.UNIT_MANAGER, unit.pk)
        ):
            raise serializers.ValidationError("You may not manage this unit.")
        if (
            self.instance
            and self.instance.unit_id != unit.pk
            and (self.instance.programs.exists() or self.instance.courses.exists())
        ):
            raise serializers.ValidationError(
                "A department with programs or courses cannot change units."
            )
        return unit

    def validate_name(self, value):
        queryset = Department.objects.filter(name__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A department with this name already exists."
            )
        return value

    def validate_code(self, value):
        value = value.upper()
        if not 2 <= len(value) <= 8 or not value.isalnum() or not value.isascii():
            raise serializers.ValidationError("Use 2–8 uppercase letters or digits.")
        queryset = Department.objects.filter(code__iexact=value)
        if self.instance:
            queryset = queryset.exclude(pk=self.instance.pk)
        if queryset.exists():
            raise serializers.ValidationError(
                "A department with this code already exists."
            )
        return value

    class Meta:
        model = Department
        fields = ("unit", "campus", "name", "code", "is_active")


class ProgramSerializer(serializers.ModelSerializer):
    def validate(self, attrs):
        department = attrs.get("department", getattr(self.instance, "department", None))
        if (
            self.instance
            and department
            and department.pk != self.instance.department_id
            and self.instance.courses.exists()
        ):
            raise serializers.ValidationError(
                {"department": "A program with courses cannot change departments."}
            )
        return attrs

    class Meta:
        model = Program
        fields = ("id", "unit", "department", "name", "code", "is_active")
        read_only_fields = ("id", "unit")


class AcademicPeriodSerializer(serializers.ModelSerializer):
    kind = serializers.ChoiceField(
        choices=AcademicPeriod.Kind.choices, required=True, allow_null=True
    )
    unit = serializers.PrimaryKeyRelatedField(
        queryset=BusinessUnit.objects.filter(is_active=True),
        allow_null=True,
        required=False,
    )

    class Meta:
        model = AcademicPeriod
        fields = (
            "id",
            "name",
            "starts_on",
            "ends_on",
            "kind",
            "unit",
            "is_current",
            "is_active",
        )
        read_only_fields = ("id",)

    def validate(self, attrs):
        if "kind" in attrs and attrs["kind"] is None:
            raise serializers.ValidationError(
                {"kind": "Choose TERM or INTAKE for new and updated periods."}
            )
        if self.instance and "unit" in attrs:
            unit = attrs["unit"]
            if unit and self.instance.class_groups.exclude(course__unit=unit).exists():
                raise serializers.ValidationError(
                    {
                        "unit": "The period's unit cannot conflict with its existing classes."
                    }
                )
        return attrs
