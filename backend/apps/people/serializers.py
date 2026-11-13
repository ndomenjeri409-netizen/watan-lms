from rest_framework import serializers

from apps.accounts.roles import Role
from apps.files.models import StoredFile
from apps.org.models import BusinessUnit, Program
from apps.scheduling.models import ClassGroup

from .models import Guardian, StaffProfile, Student
from .permissions import can_register_in_unit, may_read_restricted_student


class StudentClassSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    code = serializers.CharField()
    course_title = serializers.CharField(source="course.title")
    status = serializers.CharField()


class StudentSerializer(serializers.ModelSerializer):
    home_unit_code = serializers.CharField(source="home_unit.code", read_only=True)
    class_groups = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = (
            "id",
            "user",
            "home_unit",
            "home_unit_code",
            "department",
            "program",
            "registration_number",
            "first_name",
            "last_name",
            "email",
            "phone",
            "date_of_birth",
            "national_id",
            "photo_file",
            "admission_year",
            "status",
            "is_active",
            "account_status",
            "class_groups",
            "created_at",
        )
        read_only_fields = fields

    def get_class_groups(self, student):
        user = self.context.get("request").user if self.context.get("request") else None
        enrollments = student.enrollments.select_related(
            "unit", "course__department", "class_group__course"
        )
        if user is not None and not user.has_role_global(
            Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.AUDITOR
        ):
            unit_ids = user.unit_ids_for(Role.UNIT_MANAGER, Role.BURSAR, Role.CASHIER)
            department_ids = user.department_ids_for_hod()
            teacher_class_ids = student.enrollments.filter(
                class_group__teacher_assignments__teacher=user,
                class_group__teacher_assignments__is_active=True,
            ).values_list("class_group_id", flat=True)
            from django.db.models import Q

            scope = Q(pk__in=[])
            if unit_ids:
                scope |= Q(unit_id__in=unit_ids)
            if department_ids:
                scope |= Q(course__department_id__in=department_ids)
            if user.has_role(Role.TEACHER):
                scope |= Q(class_group_id__in=teacher_class_ids)
            if user.has_role(Role.STUDENT):
                scope |= Q(student__user=user)
            enrollments = enrollments.filter(scope)

        seen = set()
        groups = []
        for enrollment in enrollments:
            class_group = enrollment.class_group
            if class_group is None or class_group.pk in seen:
                continue
            seen.add(class_group.pk)
            groups.append(class_group)
        return StudentClassSerializer(groups, many=True).data

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return data

        may_read_restricted = may_read_restricted_student(user, instance)
        if not may_read_restricted:
            for field in ("date_of_birth", "national_id", "photo_file"):
                data.pop(field, None)

        if (
            user.has_role(Role.TEACHER, Role.CASHIER)
            and not may_read_restricted
            and not user.has_role(Role.HOD)
        ):
            allowed = {
                "id",
                "first_name",
                "last_name",
                "registration_number",
                "phone",
                "class_groups",
            }
            return {field: value for field, value in data.items() if field in allowed}
        return data


class StudentRegistrationSerializer(serializers.Serializer):
    unit = serializers.PrimaryKeyRelatedField(queryset=BusinessUnit.objects.all())
    class_group = serializers.PrimaryKeyRelatedField(
        queryset=ClassGroup.objects.select_related("course__department", "course__unit")
    )
    program = serializers.PrimaryKeyRelatedField(
        queryset=Program.objects.all(), required=False, allow_null=True
    )
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=32)
    email = serializers.EmailField(required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    national_id = serializers.CharField(max_length=32, required=False, allow_blank=True)
    photo_file = serializers.PrimaryKeyRelatedField(
        queryset=StoredFile.objects.all(), required=False, allow_null=True
    )
    confirm_duplicate = serializers.BooleanField(required=False, default=False)

    def validate(self, attrs):
        request = self.context["request"]
        unit = attrs["unit"]
        class_group = attrs["class_group"]
        course = class_group.course
        if not unit.is_active or course.unit_id != unit.pk:
            raise serializers.ValidationError(
                {"class_group": "Select an active class in the selected unit."}
            )
        if (
            not class_group.is_active
            or class_group.status
            not in {ClassGroup.Status.OPEN, ClassGroup.Status.RUNNING}
            or not course.is_active
            or course.status != course.Status.PUBLISHED
        ):
            raise serializers.ValidationError(
                {"class_group": "Select an open class for a published course."}
            )
        if not can_register_in_unit(request.user, unit, course.department_id):
            raise serializers.ValidationError(
                {"unit": "You may not register students in this unit."}
            )
        program = attrs.get("program")
        if program and program.department_id != course.department_id:
            raise serializers.ValidationError(
                {"program": "The selected program belongs to another department."}
            )
        photo = attrs.get("photo_file")
        if photo and (
            photo.owner_user_id != request.user.pk
            or photo.purpose != StoredFile.Purpose.PROFILE_PHOTO
            or photo.status != StoredFile.Status.READY
        ):
            raise serializers.ValidationError(
                {"photo_file": "Select a verified profile photo that you uploaded."}
            )
        attrs["first_name"] = attrs["first_name"].strip()
        attrs["last_name"] = attrs["last_name"].strip()
        attrs["phone"] = attrs["phone"].strip()
        attrs["email"] = attrs.get("email", "").strip()
        attrs["national_id"] = attrs.get("national_id", "").strip()
        if not attrs["first_name"] or not attrs["last_name"] or not attrs["phone"]:
            raise serializers.ValidationError(
                "Name and phone are required for student registration."
            )
        return attrs


class StudentDuplicateLookupSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=128)
    phone = serializers.CharField(max_length=32, required=False)
    registration_number = serializers.CharField(max_length=64, required=False)

    def validate(self, attrs):
        if bool(attrs.get("phone")) == bool(attrs.get("registration_number")):
            raise serializers.ValidationError(
                "Provide exactly one phone number or registration number."
            )
        return attrs


class StudentDuplicateSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField(required=False)
    name = serializers.CharField()
    home_unit = serializers.CharField()
    registration_number = serializers.CharField()


class StudentDuplicateLookupMatchSerializer(serializers.Serializer):
    name = serializers.CharField()
    home_unit = serializers.CharField()
    registration_number = serializers.CharField()
    enrollment_token = serializers.CharField()


class StudentDuplicateLookupResultSerializer(serializers.Serializer):
    matches = StudentDuplicateLookupMatchSerializer(many=True)


class StudentDuplicateConflictSerializer(serializers.Serializer):
    message = serializers.CharField()
    requires_exact_lookup = serializers.BooleanField(required=False)
    requires_confirmation = serializers.BooleanField(required=False)
    lookup_token = serializers.CharField(required=False)
    visible_matches = StudentDuplicateSummarySerializer(many=True, required=False)
    matches = StudentDuplicateSummarySerializer(many=True, required=False)


class EnrollStudentInUnitSerializer(serializers.Serializer):
    class_group = serializers.PrimaryKeyRelatedField(queryset=ClassGroup.objects.all())
    student = serializers.UUIDField(required=False)
    enrollment_token = serializers.CharField(max_length=128, required=False)

    def validate(self, attrs):
        if bool(attrs.get("student")) == bool(attrs.get("enrollment_token")):
            raise serializers.ValidationError(
                "Provide either a visible student ID or an enrollment token."
            )
        return attrs


class EnrollStudentInUnitResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    student = serializers.UUIDField()
    unit = serializers.UUIDField()
    course = serializers.UUIDField()
    class_group = serializers.UUIDField()
    status = serializers.CharField()


class StudentTransferSerializer(serializers.Serializer):
    home_unit = serializers.PrimaryKeyRelatedField(
        queryset=BusinessUnit.objects.filter(is_active=True)
    )


class StudentStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Student.Status.choices)
    reason = serializers.CharField(max_length=500)


class StudentImportSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate_file(self, value):
        if value.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("The CSV file exceeds 5 MB.")
        return value


class StudentImportRowErrorSerializer(serializers.Serializer):
    row = serializers.IntegerField()
    message = serializers.CharField()


class StudentImportResultSerializer(serializers.Serializer):
    created = serializers.IntegerField()
    row_errors = StudentImportRowErrorSerializer(many=True)


class InviteStudentSerializer(serializers.Serializer):
    email = serializers.EmailField(required=False)


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

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return data
        may_read_guardians = user.has_role_global(
            Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR, Role.AUDITOR
        ) or user.has_role(Role.UNIT_MANAGER, Role.BURSAR)
        if not may_read_guardians:
            return {"id": data["id"], "student": data["student"]}
        return data
