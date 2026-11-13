from rest_framework import serializers

from apps.academics.models import Course
from apps.accounts.models import RoleAssignment, User
from apps.accounts.roles import Role

from .models import ClassGroup, ClassTeacher, Room, TimetableSlot
from .permissions import can_manage_department_schedule


class ClassTeacherSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.display_name", read_only=True)
    teacher_email = serializers.EmailField(source="teacher.email", read_only=True)

    class Meta:
        model = ClassTeacher
        validators = ()
        fields = (
            "id",
            "unit",
            "class_group",
            "teacher",
            "teacher_name",
            "teacher_email",
            "role",
            "is_active",
        )
        read_only_fields = ("id", "unit", "teacher_name", "teacher_email", "is_active")

    def validate(self, attrs):
        user = self.context["request"].user
        class_group = attrs.get(
            "class_group", getattr(self.instance, "class_group", None)
        )
        teacher = attrs.get("teacher", getattr(self.instance, "teacher", None))
        role = attrs.get("role", getattr(self.instance, "role", None))

        if (
            class_group
            and not ClassGroup.objects.for_user(user).filter(pk=class_group.pk).exists()
        ):
            raise serializers.ValidationError(
                {"class_group": "You may not assign teachers to this class."}
            )
        if class_group and not can_manage_department_schedule(
            user, class_group.course.department
        ):
            raise serializers.ValidationError(
                {"class_group": "You may only manage classes in your assigned scope."}
            )
        if (
            teacher
            and class_group
            and not RoleAssignment.objects.filter(
                user=teacher,
                role=Role.TEACHER,
                unit_id=class_group.course.unit_id,
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"teacher": "Select an active teacher assigned to this unit."}
            )
        if (
            role == ClassTeacher.Role.ASSISTANT
            and class_group
            and teacher
            and class_group.teacher_assignments.filter(
                teacher=teacher,
                role=ClassTeacher.Role.LEAD,
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"role": "Assign another lead teacher before changing this role."}
            )
        return attrs


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ("id", "department", "name", "code", "capacity", "is_active")
        read_only_fields = ("id",)

    def validate_department(self, department):
        user = self.context["request"].user
        if department is None and not user.has_role_global(
            Role.SUPER_ADMIN, Role.ADMIN
        ):
            if user.has_role(Role.HOD, Role.UNIT_MANAGER):
                raise serializers.ValidationError(
                    "Assign the room to a department in your scope."
                )
            return department
        if department and not can_manage_department_schedule(user, department):
            raise serializers.ValidationError(
                "You may only manage rooms in your assigned scope."
            )
        return department


class ClassGroupSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    lead_teacher = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), write_only=True, required=False
    )
    lead_teacher_id = serializers.SerializerMethodField()
    lead_teacher_name = serializers.SerializerMethodField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is None:
            self.fields["lead_teacher"].required = True
            self.fields["academic_period"].required = True

    class Meta:
        model = ClassGroup
        fields = (
            "id",
            "course",
            "course_title",
            "lead_teacher",
            "lead_teacher_id",
            "lead_teacher_name",
            "academic_period",
            "name",
            "code",
            "capacity",
            "status",
            "is_active",
        )
        read_only_fields = (
            "id",
            "course_title",
            "lead_teacher_id",
            "lead_teacher_name",
            "status",
        )

    def create(self, validated_data):
        validated_data.pop("lead_teacher")
        return super().create(validated_data)

    def get_lead_teacher_name(self, obj) -> str | None:
        lead_assignment = self._get_lead_assignment(obj)
        if lead_assignment is None:
            return None
        return lead_assignment.teacher.display_name or lead_assignment.teacher.email

    def get_lead_teacher_id(self, obj) -> str | None:
        lead_assignment = self._get_lead_assignment(obj)
        return str(lead_assignment.teacher_id) if lead_assignment else None

    @staticmethod
    def _get_lead_assignment(obj):
        return next(
            (
                assignment
                for assignment in obj.teacher_assignments.all()
                if assignment.role == ClassTeacher.Role.LEAD and assignment.is_active
            ),
            None,
        )

    def validate(self, attrs):
        user = self.context["request"].user
        course = attrs.get("course", getattr(self.instance, "course", None))
        lead_teacher = attrs.get("lead_teacher")
        creating = self.instance is None
        has_unit_scope = bool(
            course and can_manage_department_schedule(user, course.department)
        )
        has_teacher_scope = bool(
            course
            and user.has_role(Role.TEACHER)
            and course.teacher_assignments.filter(
                teacher=user, can_edit_content=True, is_active=True
            ).exists()
        )
        if course and not course.is_active:
            raise serializers.ValidationError({"course": "Select an active course."})
        if creating and course and course.status != Course.Status.PUBLISHED:
            raise serializers.ValidationError(
                {"course": "Publish the course before creating a class."}
            )
        academic_period = attrs.get(
            "academic_period", getattr(self.instance, "academic_period", None)
        )
        if creating and not academic_period:
            raise serializers.ValidationError(
                {"academic_period": "Select an academic period."}
            )
        if creating and not lead_teacher:
            raise serializers.ValidationError(
                {"lead_teacher": "Select a lead teacher for this class."}
            )
        if not creating and "lead_teacher" in attrs:
            raise serializers.ValidationError(
                {"lead_teacher": "Update the lead through class teacher assignments."}
            )
        if creating and academic_period and academic_period.kind is None:
            raise serializers.ValidationError(
                {"academic_period": "Select a period classified as TERM or INTAKE."}
            )
        if creating and academic_period and not academic_period.is_active:
            raise serializers.ValidationError(
                {"academic_period": "Select an active academic period."}
            )
        if (
            academic_period
            and course
            and academic_period.unit_id
            and academic_period.unit_id != course.unit_id
        ):
            raise serializers.ValidationError(
                {"academic_period": "Select a period in the course's business unit."}
            )
        if creating and not attrs.get("name", "").strip():
            raise serializers.ValidationError({"name": "Enter a cohort name."})
        capacity = attrs.get("capacity", getattr(self.instance, "capacity", 40))
        if capacity < 1:
            raise serializers.ValidationError(
                {"capacity": "Capacity must be at least one."}
            )
        if course and not (has_unit_scope or has_teacher_scope):
            raise serializers.ValidationError(
                {"course": "You may only schedule courses in your assigned scope."}
            )
        if (
            course
            and lead_teacher
            and not RoleAssignment.objects.filter(
                user=lead_teacher,
                role=Role.TEACHER,
                unit_id=course.unit_id,
                is_active=True,
            ).exists()
        ):
            raise serializers.ValidationError(
                {"teacher": "Select an active teacher assigned to this unit."}
            )
        if (
            user.has_role(Role.TEACHER)
            and not has_unit_scope
            and lead_teacher
            and lead_teacher.pk != user.pk
        ):
            raise serializers.ValidationError(
                {"lead_teacher": "You may only assign yourself to your class group."}
            )
        return attrs


class ClassGroupTransitionSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=ClassGroup.Status.choices)


class TimetableSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableSlot
        fields = (
            "id",
            "unit",
            "class_group",
            "room",
            "weekday",
            "starts_at",
            "ends_at",
            "effective_from",
            "effective_until",
            "is_active",
        )
        read_only_fields = ("id", "unit")

    def validate(self, attrs):
        slot = self.instance
        class_group = attrs.get("class_group", getattr(slot, "class_group", None))
        room = attrs.get("room", getattr(slot, "room", None))
        weekday = attrs.get("weekday", getattr(slot, "weekday", None))
        starts_at = attrs.get("starts_at", getattr(slot, "starts_at", None))
        ends_at = attrs.get("ends_at", getattr(slot, "ends_at", None))
        effective_from = attrs.get(
            "effective_from", getattr(slot, "effective_from", None)
        )
        effective_until = attrs.get(
            "effective_until", getattr(slot, "effective_until", None)
        )
        if starts_at and ends_at and starts_at >= ends_at:
            raise serializers.ValidationError(
                {"ends_at": "End time must be after start time."}
            )
        if effective_from and effective_until and effective_until < effective_from:
            raise serializers.ValidationError(
                {"effective_until": "End date cannot be before the start date."}
            )
        if room and not room.is_active:
            raise serializers.ValidationError({"room": "Select an active room."})
        if class_group and class_group.status in {
            ClassGroup.Status.COMPLETED,
            ClassGroup.Status.CANCELLED,
        }:
            raise serializers.ValidationError(
                {"class_group": "Completed or cancelled classes cannot be scheduled."}
            )
        if (
            class_group
            and room
            and room.department_id
            not in (
                None,
                class_group.course.department_id,
            )
        ):
            raise serializers.ValidationError(
                {"room": "The room belongs to another department."}
            )
        if class_group and weekday is not None and starts_at and ends_at:
            from django.db.models import Q

            teacher_ids = set(
                class_group.teacher_assignments.filter(is_active=True).values_list(
                    "teacher_id", flat=True
                )
            )
            existing = TimetableSlot.objects.filter(
                weekday=weekday,
                is_active=True,
                class_group__is_active=True,
                starts_at__lt=ends_at,
                ends_at__gt=starts_at,
            ).filter(
                Q(effective_until__isnull=True) | Q(effective_until__gte=effective_from)
            )
            if effective_until is not None:
                existing = existing.filter(effective_from__lte=effective_until)
            if slot:
                existing = existing.exclude(pk=slot.pk)
            clashes = existing.filter(
                Q(class_group=class_group)
                | Q(
                    class_group__teacher_assignments__teacher_id__in=teacher_ids,
                    class_group__teacher_assignments__is_active=True,
                )
                | (Q(room=room) if room else Q(pk__in=[]))
            ).distinct()
            if clashes.exists():
                raise serializers.ValidationError(
                    {
                        "schedule": "This time conflicts with an existing class, teacher, or room booking."
                    }
                )
        return attrs
