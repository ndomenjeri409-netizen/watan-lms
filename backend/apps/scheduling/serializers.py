from rest_framework import serializers

from apps.accounts.roles import Role
from apps.org.models import Department

from .models import ClassGroup, Room, TimetableSlot


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ("id", "department", "name", "code", "capacity", "is_active")
        read_only_fields = ("id",)

    def validate_department(self, department):
        user = self.context["request"].user
        if user.role == Role.HOD and department is None:
            raise serializers.ValidationError(
                "Assign the room to one of your departments."
            )
        if (
            user.role == Role.HOD
            and department
            and not Department.objects.filter(
                pk=department.pk, role_scopes__user=user
            ).exists()
        ):
            raise serializers.ValidationError(
                "You may only manage rooms in your departments."
            )
        return department


class ClassGroupSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    teacher_name = serializers.CharField(source="teacher.display_name", read_only=True)

    class Meta:
        model = ClassGroup
        fields = (
            "id",
            "course",
            "course_title",
            "teacher",
            "teacher_name",
            "academic_period",
            "name",
            "code",
            "capacity",
            "is_active",
        )
        read_only_fields = ("id", "course_title", "teacher_name")

    def validate(self, attrs):
        user = self.context["request"].user
        course = attrs.get("course", getattr(self.instance, "course", None))
        teacher = attrs.get("teacher", getattr(self.instance, "teacher", None))
        if course and not course.is_active:
            raise serializers.ValidationError({"course": "Select an active course."})
        if teacher and teacher.role != Role.TEACHER:
            raise serializers.ValidationError(
                {"teacher": "The assigned user must have the Teacher role."}
            )
        if user.role == Role.TEACHER and teacher and teacher.pk != user.pk:
            raise serializers.ValidationError(
                {"teacher": "You may only assign yourself to your class group."}
            )
        if (
            user.role == Role.HOD
            and course
            and not course.department.role_scopes.filter(user=user).exists()
        ):
            raise serializers.ValidationError(
                {"course": "You may only schedule courses in your departments."}
            )
        if user.role == Role.TEACHER and course and course.created_by_id != user.id:
            raise serializers.ValidationError(
                {"course": "You may only manage groups for your courses."}
            )
        return attrs


class TimetableSlotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TimetableSlot
        fields = (
            "id",
            "class_group",
            "room",
            "weekday",
            "starts_at",
            "ends_at",
            "effective_from",
            "effective_until",
            "is_active",
        )
        read_only_fields = ("id",)

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
                | Q(class_group__teacher_id=class_group.teacher_id)
                | (Q(room=room) if room else Q(pk__in=[]))
            )
            if clashes.exists():
                raise serializers.ValidationError(
                    {
                        "schedule": "This time conflicts with an existing class, teacher, or room booking."
                    }
                )
        return attrs
