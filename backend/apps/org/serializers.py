from rest_framework import serializers

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
        if not user.has_global_read() and unit.pk not in user.unit_ids():
            raise serializers.ValidationError("You may not manage this unit.")
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
    class Meta:
        model = Program
        fields = ("id", "department", "name", "code", "is_active")
        read_only_fields = ("id",)


class AcademicPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = AcademicPeriod
        fields = ("id", "name", "starts_on", "ends_on", "is_current", "is_active")
        read_only_fields = ("id",)
