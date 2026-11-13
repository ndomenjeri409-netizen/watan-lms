from django.db import transaction
from django.db.models import Prefetch
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.enrollment.models import Enrollment
from common.audit import get_object_audit_scope, record_audit
from common.scoping import ScopedViewSetMixin

from .models import ClassGroup, ClassTeacher, Room, TimetableSlot
from .permissions import (
    ClassTeacherPermission,
    SchedulingPermission,
    can_manage_course_schedule,
    can_manage_scheduled_class,
)
from .serializers import (
    ClassGroupSerializer,
    ClassGroupTransitionSerializer,
    ClassTeacherSerializer,
    RoomSerializer,
    TimetableSlotSerializer,
)
from .services import transition_class_group


class AuditedSchedulingViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = (SchedulingPermission,)

    def after_create(self, instance, validated_data):
        pass

    def after_update(self, instance, before):
        pass

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            self.after_create(instance, serializer.validated_data)
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
            self.after_update(instance, before)
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
    queryset = (
        ClassGroup.objects.select_related("course__department", "academic_period")
        .prefetch_related(
            Prefetch(
                "teacher_assignments",
                queryset=ClassTeacher.objects.select_related("teacher"),
            )
        )
        .all()
    )
    serializer_class = ClassGroupSerializer
    search_fields = (
        "name",
        "code",
        "course__title",
        "teacher_assignments__teacher__display_name",
    )
    ordering_fields = ("name", "code", "course__title")
    filterset_fields = ("course", "academic_period", "status", "is_active")

    def perform_create(self, serializer):
        course = serializer.validated_data["course"]
        if not can_manage_course_schedule(self.request.user, course):
            raise PermissionDenied(
                "You may only create classes for courses you author."
            )
        super().perform_create(serializer)

    def perform_update(self, serializer):
        with transaction.atomic():
            class_group = ClassGroup.objects.select_for_update().get(
                pk=serializer.instance.pk
            )
            if class_group.status in {
                ClassGroup.Status.COMPLETED,
                ClassGroup.Status.CANCELLED,
            }:
                raise ValidationError(
                    {"status": "Completed or cancelled classes are locked."}
                )
            serializer.instance = class_group
            super().perform_update(serializer)

    def after_create(self, instance, validated_data):
        ClassTeacher.objects.create(
            class_group=instance,
            teacher=validated_data["lead_teacher"],
            unit=instance.course.unit,
            role=ClassTeacher.Role.LEAD,
        )

    @extend_schema(
        request=ClassGroupTransitionSerializer, responses=ClassGroupSerializer
    )
    @action(detail=True, methods=("post",))
    def transition(self, request, pk=None):
        class_group = self.get_object()
        if not can_manage_scheduled_class(request.user, class_group):
            raise PermissionDenied("You may not change this class's status.")
        serializer = ClassGroupTransitionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        class_group = transition_class_group(
            class_group_id=class_group.pk,
            target=serializer.validated_data["status"],
            actor=request.user,
        )
        return Response(self.get_serializer(class_group).data)

    def perform_destroy(self, instance):
        with transaction.atomic():
            instance = ClassGroup.objects.select_for_update().get(pk=instance.pk)
            if Enrollment.objects.filter(
                class_group=instance, status=Enrollment.Status.ACTIVE
            ).exists():
                raise ValidationError(
                    {
                        "class_group": "Complete or cancel active enrollments before archiving this class."
                    }
                )
            super().perform_destroy(instance)


class ClassTeacherViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = ClassTeacher.objects.select_related(
        "unit", "class_group__course", "teacher"
    ).all()
    serializer_class = ClassTeacherSerializer
    permission_classes = (ClassTeacherPermission,)
    assignment_management = True
    http_method_names = ("get", "post", "delete", "head", "options")
    filterset_fields = ("class_group", "teacher", "role", "is_active")
    search_fields = ("class_group__name", "teacher__display_name", "teacher__email")
    ordering_fields = ("created_at", "teacher__display_name")

    def perform_create(self, serializer):
        data = serializer.validated_data
        with transaction.atomic():
            class_group = ClassGroup.objects.select_for_update().get(
                pk=data["class_group"].pk
            )
            if class_group.status in {
                ClassGroup.Status.COMPLETED,
                ClassGroup.Status.CANCELLED,
            }:
                raise ValidationError(
                    {"class_group": "Completed or cancelled classes are locked."}
                )
            if data.get("role") == ClassTeacher.Role.LEAD:
                previous_leads = (
                    ClassTeacher.objects.select_for_update()
                    .filter(
                        class_group=class_group,
                        role=ClassTeacher.Role.LEAD,
                        is_active=True,
                    )
                    .exclude(teacher=data["teacher"])
                )
                for previous_lead in previous_leads:
                    before_lead = self.get_serializer(previous_lead).data
                    previous_lead.role = ClassTeacher.Role.ASSISTANT
                    previous_lead.save(update_fields=("role", "updated_at"))
                    record_audit(
                        actor=self.request.user,
                        action="class_teacher_role_updated",
                        obj=previous_lead,
                        unit=previous_lead.unit,
                        before=before_lead,
                        after=self.get_serializer(previous_lead).data,
                    )
            assignment, created = ClassTeacher.objects.get_or_create(
                class_group=class_group,
                teacher=data["teacher"],
                defaults={
                    "unit": class_group.course.unit,
                    "role": data.get("role", ClassTeacher.Role.ASSISTANT),
                },
            )
            before = None
            if not created:
                before = self.get_serializer(assignment).data
            previous_role = assignment.role
            was_active = assignment.is_active
            assignment.role = data.get("role", ClassTeacher.Role.ASSISTANT)
            assignment.is_active = True
            assignment.save(update_fields=("role", "is_active", "updated_at"))
            record_audit(
                actor=self.request.user,
                action=(
                    "class_teacher_assigned"
                    if created
                    else "class_teacher_role_updated"
                    if was_active and previous_role != assignment.role
                    else "class_teacher_reactivated"
                ),
                obj=assignment,
                unit=assignment.unit,
                before=before,
                after=self.get_serializer(assignment).data,
            )
        serializer.instance = assignment

    def perform_destroy(self, instance):
        from rest_framework.exceptions import ValidationError

        if instance.role == ClassTeacher.Role.LEAD:
            raise ValidationError(
                {
                    "role": "Change the class group's lead teacher instead of removing this assignment."
                }
            )
        before = self.get_serializer(instance).data
        with transaction.atomic():
            class_group = ClassGroup.objects.select_for_update().get(
                pk=instance.class_group_id
            )
            if class_group.status in {
                ClassGroup.Status.COMPLETED,
                ClassGroup.Status.CANCELLED,
            }:
                raise ValidationError(
                    {"class_group": "Completed or cancelled classes are locked."}
                )
            instance.is_active = False
            instance.save(update_fields=("is_active", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="class_teacher_unassigned",
                obj=instance,
                unit=instance.unit,
                before=before,
                after=self.get_serializer(instance).data,
            )


class TimetableSlotViewSet(AuditedSchedulingViewSet):
    teacher_schedule_management = True
    queryset = TimetableSlot.objects.select_related(
        "class_group__course__department", "room"
    ).all()
    serializer_class = TimetableSlotSerializer
    search_fields = ("class_group__name", "class_group__course__title", "room__name")
    ordering_fields = ("weekday", "starts_at", "ends_at")
    filterset_fields = ("class_group", "room", "weekday", "is_active")

    def perform_create(self, serializer):
        if not can_manage_scheduled_class(
            self.request.user, serializer.validated_data["class_group"]
        ):
            raise PermissionDenied("You may only manage your own timetable.")
        super().perform_create(serializer)

    def perform_update(self, serializer):
        group = serializer.validated_data.get(
            "class_group", serializer.instance.class_group
        )
        if not can_manage_scheduled_class(self.request.user, group):
            raise PermissionDenied("You may only manage your own timetable.")
        super().perform_update(serializer)
