from rest_framework import serializers

from .models import Guardian, StaffProfile, Student


class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = (
            "id",
            "user",
            "department",
            "program",
            "registration_number",
            "first_name",
            "last_name",
            "email",
            "phone",
            "admission_year",
            "is_active",
            "created_at",
        )
        read_only_fields = fields


class StaffProfileSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source="user.email", read_only=True)
    display_name = serializers.CharField(source="user.display_name", read_only=True)
    role = serializers.CharField(source="user.role", read_only=True)

    class Meta:
        model = StaffProfile
        fields = (
            "id",
            "user",
            "user_email",
            "display_name",
            "role",
            "department",
            "job_title",
            "phone",
            "is_active",
        )
        read_only_fields = ("id", "user", "user_email", "display_name", "role")


class GuardianSerializer(serializers.ModelSerializer):
    class Meta:
        model = Guardian
        fields = (
            "id",
            "student",
            "full_name",
            "relationship",
            "email",
            "phone",
            "is_active",
        )
        read_only_fields = ("id",)
