from django.db import transaction
from rest_framework import viewsets

from apps.accounts.roles import ADMIN_ROLES, Role
from common.audit import get_object_audit_scope, record_audit
from common.scoping import ScopedViewSetMixin

from .models import ClassGroup, Room, TimetableSlot
from .permissions import SchedulingPermission
from .serializers import ClassGroupSerializer, RoomSerializer, TimetableSlotSerializer


class AuditedSchedulingViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = (SchedulingPermission,)

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            unit, group_level = get_object_audit_scope(instance)
            record_audit(
                actor=self.request.user,
                action="created",
                obj=instance,
                unit=unit,
                group_level=group_level,
                after=self.get_serializer(instance).data,
            )

    def perform_update(self, serializer):
        before = self.get_serializer(serializer.instance).data
        with transaction.atomic():
            instance = serializer.save()
            unit, group_level = get_object_audit_scope(instance)
            record_audit(
                actor=self.request.user,
                action="updated",
                obj=instance,
                unit=unit,
                group_level=group_level,
                before=before,
                after=self.get_serializer(instance).data,
            )

    def perform_destroy(self, instance):
        before = self.get_serializer(instance).data
        with transaction.atomic():
            instance.is_active = False
            instance.save(update_fields=("is_active", "updated_at"))
            unit, group_level = get_object_audit_scope(instance)
            record_audit(
                actor=self.request.user,
                action="archived",
                obj=instance,
                unit=unit,
                group_level=group_level,
                before=before,
                after=self.get_serializer(instance).data,
            )


class RoomViewSet(AuditedSchedulingViewSet):
    queryset = Room.objects.select_related("department").all()
    serializer_class = RoomSerializer
    search_fields = ("name", "code")
    ordering_fields = ("name", "capacity")
    filterset_fields = ("department", "is_active")


class ClassGroupViewSet(AuditedSchedulingViewSet):
    teacher_schedule_management = True
    queryset = ClassGroup.objects.select_related(
        "course__department", "teacher", "academic_period"
    ).all()
    serializer_class = ClassGroupSerializer
    search_fields = ("name", "code", "course__title", "teacher__display_name")
    ordering_fields = ("name", "code", "course__title")
    filterset_fields = ("course", "teacher", "academic_period", "is_active")

    def get_permissions(self):
        permissions = super().get_permissions()
        if self.action in {"list", "retrieve"}:
            return permissions
        return permissions

    def perform_create(self, serializer):
        if (
            self.request.user.role not in ADMIN_ROLES | {Role.HOD}
            and serializer.validated_data["course"].created_by_id
            != self.request.user.id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage groups for your courses.")
        super().perform_create(serializer)


class TimetableSlotViewSet(AuditedSchedulingViewSet):
    teacher_schedule_management = True
    queryset = TimetableSlot.objects.select_related(
        "class_group__course__department", "class_group__teacher", "room"
    ).all()
    serializer_class = TimetableSlotSerializer
    search_fields = ("class_group__name", "class_group__course__title", "room__name")
    ordering_fields = ("weekday", "starts_at", "ends_at")
    filterset_fields = ("class_group", "room", "weekday", "is_active")

    def perform_create(self, serializer):
        if (
            self.request.user.role not in ADMIN_ROLES | {Role.HOD}
            and serializer.validated_data["class_group"].teacher_id
            != self.request.user.id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage your own timetable.")
        super().perform_create(serializer)

    def perform_update(self, serializer):
        group = serializer.validated_data.get(
            "class_group", serializer.instance.class_group
        )
        if (
            self.request.user.role not in ADMIN_ROLES | {Role.HOD}
            and group.teacher_id != self.request.user.id
        ):
            from rest_framework.exceptions import PermissionDenied

            raise PermissionDenied("You may only manage your own timetable.")
        super().perform_update(serializer)
