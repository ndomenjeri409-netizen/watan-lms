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
from apps.enrollment.models import Enrollment
from apps.scheduling.models import ClassGroup
from common.audit import get_object_audit_scope, record_audit
from common.scoping import ScopedViewSetMixin

from .models import AttendanceRecord, AttendanceSession
from .permissions import AttendancePermission
from .serializers import (
    AttendanceMarkResponseSerializer,
    AttendanceMarkSerializer,
    AttendanceRecordSerializer,
    AttendanceRosterEntrySerializer,
    AttendanceSessionSerializer,
    CheckInSerializer,
    OpenSessionSerializer,
    QrIssueSerializer,
)
from .services import check_in_with_qr, issue_qr_token


def may_manage_attendance(user, group):
    return bool(
        user.has_role_global(*ADMIN_ROLES)
        or (
            user.has_role(Role.HOD)
            and group.course.department_id in user.department_ids_for_hod()
        )
        or user.has_role_for_unit(Role.UNIT_MANAGER, group.course.unit_id)
        or (user.has_role(Role.TEACHER) and group.has_teacher(user))
    )


class SessionAlreadyOpen(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Attendance is already open for this class."
    default_code = "session_already_open"


class AttendanceSessionViewSet(ScopedViewSetMixin, viewsets.GenericViewSet):
    queryset = AttendanceSession.objects.select_related(
        "class_group__course__department", "opened_by"
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
        if group.status != ClassGroup.Status.RUNNING:
            raise ValidationError(
                {"class_group": "Move the class to RUNNING before opening attendance."}
            )
        if not may_manage_attendance(request.user, group):
            raise PermissionDenied(
                "You may only open attendance within your assigned scope."
            )
        try:
            with transaction.atomic():
                group = ClassGroup.objects.select_for_update().get(pk=group.pk)
                if not group.is_active or group.status != ClassGroup.Status.RUNNING:
                    raise ValidationError(
                        {
                            "class_group": "Move an active class to RUNNING before opening attendance."
                        }
                    )
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

    @extend_schema(responses=AttendanceRosterEntrySerializer(many=True))
    @action(detail=True, methods=("get",))
    def roster(self, request, pk=None):
        session = self.get_object()
        if not may_manage_attendance(request.user, session.class_group):
            raise PermissionDenied("You may not view this class attendance roster.")
        enrollments = (
            Enrollment.objects.filter(
                class_group_id=session.class_group_id,
                status=Enrollment.Status.ACTIVE,
            )
            .select_related("student")
            .order_by("student__registration_number")
        )
        record_by_student = {
            record.student_id: record
            for record in AttendanceRecord.objects.filter(
                session=session, student_id__in=enrollments.values("student_id")
            )
        }
        entries = [
            {
                "student": enrollment.student_id,
                "student_name": (
                    f"{enrollment.student.first_name} {enrollment.student.last_name}"
                ),
                "registration_number": enrollment.student.registration_number,
                "status": (
                    record_by_student[enrollment.student_id].status
                    if enrollment.student_id in record_by_student
                    else None
                ),
                "checked_in_at": (
                    record_by_student[enrollment.student_id].checked_in_at
                    if enrollment.student_id in record_by_student
                    else None
                ),
            }
            for enrollment in enrollments
        ]
        page = self.paginate_queryset(entries)
        if page is not None:
            return self.get_paginated_response(
                AttendanceRosterEntrySerializer(page, many=True).data
            )
        return Response(AttendanceRosterEntrySerializer(entries, many=True).data)

    @extend_schema(
        request=AttendanceMarkSerializer,
        responses=AttendanceMarkResponseSerializer,
    )
    @action(detail=True, methods=("post",))
    def mark(self, request, pk=None):
        session = self.get_object()
        if not may_manage_attendance(request.user, session.class_group):
            raise PermissionDenied("You may only mark attendance within your assigned scope.")
        serializer = AttendanceMarkSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        marks = serializer.validated_data["records"]
        student_ids = [mark["student"] for mark in marks]

        with transaction.atomic():
            session = (
                AttendanceSession.objects.select_for_update()
                .select_related("class_group__course__department")
                .get(pk=session.pk)
            )
            group = session.class_group
            if not group.is_active or group.status == ClassGroup.Status.CANCELLED:
                raise ValidationError(
                    {"session": "Attendance cannot be marked for a cancelled class."}
                )
            roster_ids = set(
                Enrollment.objects.select_for_update()
                .filter(
                    class_group=group,
                    status=Enrollment.Status.ACTIVE,
                )
                .values_list("student_id", flat=True)
            )
            out_of_roster = sorted(
                str(student_id)
                for student_id in set(student_ids) - roster_ids
            )
            if out_of_roster:
                raise ValidationError(
                    {"records": {"students": out_of_roster}}
                )

            for mark in marks:
                record = (
                    AttendanceRecord.objects.select_for_update()
                    .filter(session=session, student_id=mark["student"])
                    .first()
                )
                previous_status = record.status if record else None
                if record is None:
                    record = AttendanceRecord.objects.create(
                        session=session,
                        student_id=mark["student"],
                        status=mark["status"],
                    )
                elif record.status != mark["status"]:
                    record.status = mark["status"]
                    record.save(update_fields=("status", "updated_at"))
                else:
                    continue
                record_audit(
                    actor=request.user,
                    action="attendance_record_marked",
                    obj=record,
                    unit=group.course.unit,
                    before={"status": previous_status} if previous_status else {},
                    after={
                        "session_id": str(session.id),
                        "student_id": str(record.student_id),
                        "status": record.status,
                        "source": "STAFF",
                    },
                )

            records = AttendanceRecord.objects.filter(
                session=session, student_id__in=student_ids
            ).select_related("student").order_by("student__registration_number")
        return Response(
            {"records": AttendanceRecordSerializer(records, many=True).data}
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
            visible_sessions = self.get_queryset().filter(pk=pk).values("pk")
            session = AttendanceSession.objects.select_for_update().get(
                pk__in=visible_sessions
            )
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
