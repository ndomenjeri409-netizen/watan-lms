import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from firebase_admin import auth as fb_auth
from firebase_admin.exceptions import FirebaseError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    PermissionDenied,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.org.models import BusinessUnit
from common.audit import get_object_unit, record_audit
from common.permissions import ReadOnlyRoleWritePermission, UserManagementPermission

from . import authentication
from .api_serializers import (
    InviteUserSerializer,
    RoleAssignmentCreateSerializer,
    UserSerializer,
)
from .management import assert_role_assignment
from .models import RoleAssignment, RoleScope
from .roles import Role
from .serializers import MeSerializer, MeUpdateSerializer

User = get_user_model()
logger = logging.getLogger(__name__)


class MeView(APIView):
    permission_classes = (IsAuthenticated, ReadOnlyRoleWritePermission)

    @extend_schema(responses=MeSerializer)
    def get(self, request):
        return Response(MeSerializer(request.user).data)

    @extend_schema(request=MeUpdateSerializer, responses=MeSerializer)
    def patch(self, request):
        serializer = MeUpdateSerializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(MeSerializer(request.user).data)


class ServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Identity provisioning is temporarily unavailable."
    default_code = "service_unavailable"


class UserViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = (UserManagementPermission, ReadOnlyRoleWritePermission)
    search_fields = ("email", "display_name")
    ordering_fields = ("email", "display_name", "created_at")
    filterset_fields = ("is_active",)

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .for_user(self.request.user)
            .prefetch_related(
                "role_scopes",
                "assignments__unit",
                "student_profile",
            )
        )
        role = self.request.query_params.get("role")
        if not role:
            return queryset
        if role == Role.STUDENT:
            return queryset.filter(student_profile__isnull=False)
        if role not in Role.values:
            return queryset.none()
        return queryset.filter(
            assignments__is_active=True, assignments__role=role
        ).distinct()

    @extend_schema(request=InviteUserSerializer, responses={201: UserSerializer})
    @action(detail=False, methods=("post",), url_path="invite")
    def invite(self, request):
        serializer = InviteUserSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        assert_role_assignment(request.user, values["role"])

        try:
            authentication._ensure_firebase()
        except AuthenticationFailed as exc:
            raise ServiceUnavailable() from exc

        authentication.verify_revoked_token(request)
        try:
            firebase_user = fb_auth.create_user(
                email=values["email"],
                display_name=values["display_name"] or values["email"].split("@")[0],
            )
        except FirebaseError as exc:
            if isinstance(exc, fb_auth.EmailAlreadyExistsError):
                raise ValidationError(
                    {"email": "An account with this email already exists."}
                ) from exc
            raise ServiceUnavailable() from exc

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    firebase_uid=firebase_user.uid,
                    email=values["email"],
                    display_name=values["display_name"],
                    role=values["role"],
                    unit=BusinessUnit.objects.get(pk=values["unit_id"])
                    if values.get("unit_id")
                    else None,
                    granted_by=request.user,
                )
                if values["role"] == Role.HOD:
                    RoleScope.objects.bulk_create(
                        [
                            RoleScope(user=user, department_id=department_id)
                            for department_id in values.get("department_ids", [])
                        ]
                    )
                audit_unit = get_object_unit(user)
                record_audit(
                    actor=request.user,
                    action="invited",
                    obj=user,
                    unit=audit_unit,
                    group_level=audit_unit is None,
                    after={
                        "email": user.email,
                        "role": user.role,
                        "department_ids": [
                            str(value) for value in values.get("department_ids", [])
                        ],
                    },
                )
        except Exception:
            try:
                fb_auth.delete_user(firebase_user.uid)
            except FirebaseError:
                logger.exception("Could not remove Firebase user after failed invite.")
            raise

        return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        request=RoleAssignmentCreateSerializer,
        responses={200: UserSerializer, 201: UserSerializer},
    )
    @action(detail=True, methods=("post",), url_path="assignments")
    def assignments(self, request, pk=None):
        user = self.get_object()
        serializer = RoleAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        assert_role_assignment(request.user, values["role"], target=user)

        authentication._ensure_firebase()
        authentication.verify_revoked_token(request)

        unit = values.get("unit")
        with transaction.atomic():
            assignment, created = RoleAssignment.objects.get_or_create(
                user=user,
                role=values["role"],
                unit=unit,
                defaults={
                    "is_active": True,
                    "granted_by": request.user,
                },
            )
            changed = created or not assignment.is_active
            existing_department_ids = set()
            new_department_ids = values.get("department_ids", [])
            if values["role"] == Role.HOD:
                existing_department_ids = set(
                    RoleScope.objects.filter(
                        user=user,
                        department__unit=unit,
                    ).values_list("department_id", flat=True)
                )
            before = {
                "role": assignment.role,
                "unit_id": str(assignment.unit_id) if assignment.unit_id else None,
                "is_active": assignment.is_active,
            }
            if changed and not created:
                assignment.is_active = True
                assignment.granted_by = request.user
                assignment.save(update_fields=("is_active", "granted_by", "updated_at"))
            if values["role"] == Role.HOD:
                RoleScope.objects.bulk_create(
                    [
                        RoleScope(user=user, department_id=department_id)
                        for department_id in values.get("department_ids", [])
                    ],
                    ignore_conflicts=True,
                )
            scope_changed = bool(set(new_department_ids) - existing_department_ids)
            if changed or scope_changed:
                record_audit(
                    actor=request.user,
                    action="assignment_changed",
                    obj=assignment,
                    unit=unit,
                    group_level=unit is None,
                    before=(
                        {
                            **before,
                            "department_ids": [
                                str(value)
                                for value in sorted(existing_department_ids, key=str)
                            ],
                        }
                        if not created
                        else {}
                    ),
                    after={
                        "role": assignment.role,
                        "unit_id": str(assignment.unit_id)
                        if assignment.unit_id
                        else None,
                        "is_active": assignment.is_active,
                        "department_ids": [
                            str(value)
                            for value in sorted(
                                existing_department_ids | set(new_department_ids),
                                key=str,
                            )
                        ],
                    },
                )
        user.clear_role_cache()
        user._prefetched_objects_cache.pop("assignments", None)
        user._prefetched_objects_cache.pop("role_scopes", None)
        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(
        parameters=[
            OpenApiParameter(
                "assignment_id",
                OpenApiTypes.UUID,
                OpenApiParameter.PATH,
            )
        ],
        responses=UserSerializer,
    )
    @action(
        detail=True,
        methods=("delete",),
        url_path=r"assignments/(?P<assignment_id>[^/.]+)",
    )
    def deactivate_assignment(self, request, pk=None, assignment_id=None):
        user = self.get_object()
        assignment = user.assignments.filter(pk=assignment_id).first()
        if assignment is None:
            return Response(status=status.HTTP_404_NOT_FOUND)
        assert_role_assignment(request.user, assignment.role, target=user)

        authentication._ensure_firebase()
        authentication.verify_revoked_token(request)

        with transaction.atomic():
            if assignment.is_active and assignment.role == Role.SUPER_ADMIN:
                if request.user.pk == user.pk:
                    raise PermissionDenied(
                        "You cannot remove your own SUPER_ADMIN assignment."
                    )
                super_admin_users = list(
                    User.objects.filter(
                        assignments__role=Role.SUPER_ADMIN,
                        assignments__is_active=True,
                        assignments__unit__isnull=True,
                    )
                    .values_list("pk", flat=True)
                    .distinct()
                )
                list(
                    User.objects.select_for_update()
                    .filter(pk__in=super_admin_users)
                    .values_list("pk", flat=True)
                )
                active_super_admin_users = list(
                    User.objects.filter(
                        assignments__role=Role.SUPER_ADMIN,
                        assignments__is_active=True,
                        assignments__unit__isnull=True,
                    )
                    .filter(pk__in=super_admin_users)
                    .values_list("pk", flat=True)
                    .distinct()
                )
                if len(active_super_admin_users) <= 1:
                    raise PermissionDenied(
                        "The last active SUPER_ADMIN assignment cannot be removed."
                    )

            before = {
                "role": assignment.role,
                "unit_id": str(assignment.unit_id) if assignment.unit_id else None,
                "is_active": assignment.is_active,
            }
            if assignment.is_active:
                assignment.is_active = False
                assignment.save(update_fields=("is_active", "updated_at"))
                if assignment.role == Role.HOD and assignment.unit_id:
                    RoleScope.objects.filter(
                        user=user,
                        department__unit_id=assignment.unit_id,
                    ).delete()
                record_audit(
                    actor=request.user,
                    action="assignment_deactivated",
                    obj=assignment,
                    unit=assignment.unit,
                    group_level=assignment.unit_id is None,
                    before=before,
                    after={**before, "is_active": False},
                )
        user.clear_role_cache()
        user._prefetched_objects_cache.pop("assignments", None)
        user._prefetched_objects_cache.pop("role_scopes", None)
        return Response(UserSerializer(user).data)
