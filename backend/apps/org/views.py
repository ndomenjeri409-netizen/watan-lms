from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from common.audit import get_object_unit, record_audit
from common.permissions import OrgManagementPermission
from common.scoping import ScopedViewSetMixin

from .models import AcademicPeriod, BusinessUnit, Campus, Department, Program
from .serializers import (
    AcademicPeriodSerializer,
    BusinessUnitSerializer,
    CampusSerializer,
    DepartmentSerializer,
    DepartmentWriteSerializer,
    ProgramSerializer,
)


class BusinessUnitListView(ListAPIView):
    queryset = BusinessUnit.objects.none()
    serializer_class = BusinessUnitSerializer
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return BusinessUnit.objects.none()
        if (
            self.request.user.has_global_read()
            or self.request.user.has_group_bursar_assignment()
        ):
            return BusinessUnit.objects.filter(is_active=True)
        return BusinessUnit.objects.filter(
            id__in=self.request.user.unit_ids(), is_active=True
        )


class ScopedOrgViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    permission_classes = (OrgManagementPermission,)

    def perform_create(self, serializer):
        with transaction.atomic():
            instance = serializer.save()
            record_audit(
                actor=self.request.user,
                action="created",
                instance=instance,
                unit=get_object_unit(instance),
                after=serializer.data,
            )

    def perform_update(self, serializer):
        before = self.get_serializer(instance=serializer.instance).data
        with transaction.atomic():
            instance = serializer.save()
            record_audit(
                actor=self.request.user,
                action="updated",
                instance=instance,
                unit=get_object_unit(instance),
                before=before,
                after=self.get_serializer(instance=instance).data,
            )

    def perform_destroy(self, instance):
        before = self.get_serializer(instance=instance).data
        with transaction.atomic():
            instance.is_active = False
            instance.save(update_fields=("is_active", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="archived",
                instance=instance,
                unit=get_object_unit(instance),
                before=before,
                after=self.get_serializer(instance=instance).data,
            )


class CampusViewSet(ScopedOrgViewSet):
    queryset = Campus.objects.all()
    serializer_class = CampusSerializer
    search_fields = ("name", "code")
    ordering_fields = ("name", "code")


class DepartmentViewSet(ScopedOrgViewSet):
    queryset = (
        Department.objects.select_related("campus", "unit")
        .annotate(
            active_program_count=Count(
                "programs", filter=Q(programs__is_active=True), distinct=True
            ),
            active_course_count=Count(
                "courses", filter=Q(courses__is_active=True), distinct=True
            ),
        )
        .order_by("name", "id")
    )
    serializer_class = DepartmentSerializer
    search_fields = ("name", "code")
    ordering_fields = ("name", "code")
    filterset_fields = ("campus", "is_active", "unit")
    unit_field = "unit"

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="show_archived",
                type=bool,
                location=OpenApiParameter.QUERY,
                description="Include archived departments in the list.",
            ),
            OpenApiParameter(
                name="unit",
                type=str,
                location=OpenApiParameter.QUERY,
                description="Limit departments to an authorized business unit.",
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        show_archived = self.request.query_params.get("show_archived", "").lower()
        if show_archived not in {"true", "1"}:
            queryset = queryset.filter(archived_at__isnull=True)
        return queryset

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return DepartmentWriteSerializer
        return super().get_serializer_class()

    @extend_schema(
        request=DepartmentWriteSerializer, responses={201: DepartmentSerializer}
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        result = DepartmentSerializer(
            serializer.instance, context=self.get_serializer_context()
        )
        return Response(result.data, status=status.HTTP_201_CREATED, headers=headers)

    @extend_schema(request=DepartmentWriteSerializer, responses=DepartmentSerializer)
    def update(self, request, *args, **kwargs):
        return self._update(request, partial=False, **kwargs)

    @extend_schema(request=DepartmentWriteSerializer, responses=DepartmentSerializer)
    def partial_update(self, request, *args, **kwargs):
        return self._update(request, partial=True, **kwargs)

    def _update(self, request, *, partial, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        result = DepartmentSerializer(
            serializer.instance, context=self.get_serializer_context()
        )
        return Response(result.data)

    def perform_destroy(self, instance):
        before = self.get_serializer(instance=instance).data
        with transaction.atomic():
            instance.is_active = False
            instance.archived_at = timezone.now()
            instance.save(update_fields=("is_active", "archived_at", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="archived",
                instance=instance,
                unit=get_object_unit(instance),
                before=before,
                after=self.get_serializer(instance=instance).data,
            )


class ProgramViewSet(ScopedOrgViewSet):
    queryset = Program.objects.select_related("department").all()
    serializer_class = ProgramSerializer
    search_fields = ("name", "code")
    ordering_fields = ("name", "code")
    filterset_fields = ("department", "is_active")


class AcademicPeriodViewSet(ScopedOrgViewSet):
    queryset = AcademicPeriod.objects.all()
    serializer_class = AcademicPeriodSerializer
    search_fields = ("name",)
    ordering_fields = ("name", "starts_on", "ends_on")
    filterset_fields = ("is_current",)
