from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.roles import ADMIN_ROLES, Role
from apps.scheduling.models import ClassGroup
from common.audit import get_object_audit_scope, record_audit
from common.scoping import ScopedViewSetMixin

from .models import AttendanceRecord, AttendanceSession
from .permissions import AttendancePermission
from .serializers import (
    AttendanceRecordSerializer,
    AttendanceSessionSerializer,
    CheckInSerializer,
    OpenSessionSerializer,
    QrIssueSerializer,
)
from .services import check_in_with_qr, issue_qr_token


class SessionAlreadyOpen(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Attendance is already open for this class."
    default_code = "session_already_open"


class AttendanceSessionViewSet(ScopedViewSetMixin, viewsets.GenericViewSet):
    queryset = AttendanceSession.objects.select_related(
        "class_group__course__department", "class_group__teacher", "opened_by"
    ).annotate(record_count=Count("records"))
    serializer_class = AttendanceSessionSerializer
    permission_classes = (AttendancePermission,)
    filterset_fields = ("class_group", "is_open")
    ordering_fields = ("opened_at",)

    def list(self, request, *args, **kwargs):
        sessions = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(sessions)
        serializer = self.get_serializer(
            page if page is not None else sessions, many=True
        )
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @extend_schema(
        request=OpenSessionSerializer, responses={201: AttendanceSessionSerializer}
    )
    @action(detail=False, methods=("post",))
    def open(self, request):
        serializer = OpenSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            group = ClassGroup.objects.for_user(request.user).get(
                pk=serializer.validated_data["class_group"], is_active=True
            )
        except ClassGroup.DoesNotExist as exc:
            raise PermissionDenied(
                "You may not open attendance for this class."
            ) from exc
        if (
            request.user.role not in ADMIN_ROLES | {Role.HOD}
            and group.teacher_id != request.user.id
        ):
            raise PermissionDenied("You may only open attendance for your own class.")
        try:
            with transaction.atomic():
                session = AttendanceSession.objects.create(
                    class_group=group,
                    opened_by=request.user,
                    title=serializer.validated_data.get("title", ""),
                )
                unit, group_level = get_object_audit_scope(session)
                record_audit(
                    actor=request.user,
                    action="attendance_session_opened",
                    obj=session,
                    unit=unit,
                    group_level=group_level,
                    after={"class_group_id": str(group.id), "is_open": True},
                )
        except IntegrityError as exc:
            raise SessionAlreadyOpen() from exc
        session = self.get_queryset().get(pk=session.pk)
        return Response(
            self.get_serializer(session).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(request=None, responses=QrIssueSerializer)
    @action(detail=True, methods=("post",))
    def qr(self, request, pk=None):
        session = self.get_object()
        token, token_record = issue_qr_token(session, request.user)
        return Response(
            {
                "token": token,
                "expires_at": token_record.expires_at,
                "check_in_url": request.build_absolute_uri("/app/attendance/scan"),
            }
        )

    @extend_schema(request=None, responses=AttendanceSessionSerializer)
    @action(detail=True, methods=("post",))
    def close(self, request, pk=None):
        with transaction.atomic():
            session = self.get_queryset().select_for_update().get(pk=pk)
            self.check_object_permissions(request, session)
            if not session.is_open:
                raise ValidationError({"session": "This session is already closed."})
            session.is_open = False
            session.closed_at = timezone.now()
            session.save(update_fields=("is_open", "closed_at", "updated_at"))
            unit, group_level = get_object_audit_scope(session)
            record_audit(
                actor=request.user,
                action="attendance_session_closed",
                obj=session,
                unit=unit,
                group_level=group_level,
                after={"is_open": False, "closed_at": session.closed_at.isoformat()},
            )
        return Response(self.get_serializer(session).data)


class AttendanceRecordViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AttendanceRecord.objects.select_related(
        "student", "session__class_group__course__department"
    ).all()
    serializer_class = AttendanceRecordSerializer
    permission_classes = (AttendancePermission,)
    filterset_fields = ("session", "student", "status")
    ordering_fields = ("checked_in_at",)
    search_fields = (
        "student__registration_number",
        "student__first_name",
        "student__last_name",
    )


class CheckInView(APIView):
    permission_classes = (AttendancePermission,)

    @extend_schema(
        request=CheckInSerializer, responses={201: AttendanceRecordSerializer}
    )
    def post(self, request):
        serializer = CheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = check_in_with_qr(
            user=request.user,
            raw_token=serializer.validated_data["token"],
            client_checkin_id=serializer.validated_data.get("client_checkin_id"),
        )
        return Response(
            AttendanceRecordSerializer(record).data, status=status.HTTP_201_CREATED
        )
