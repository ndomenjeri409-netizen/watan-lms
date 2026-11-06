import logging

from django.contrib.auth import get_user_model
from django.db import transaction
from drf_spectacular.utils import extend_schema
from firebase_admin import auth as fb_auth
from firebase_admin.exceptions import FirebaseError
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    ValidationError,
)
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.org.models import BusinessUnit
from common.audit import get_object_unit, record_audit
from common.permissions import UserManagementPermission

from . import authentication
from .api_serializers import ChangeRoleSerializer, InviteUserSerializer, UserSerializer
from .management import assert_role_assignment
from .models import RoleAssignment, RoleScope
from .roles import Role
from .serializers import MeSerializer, MeUpdateSerializer

User = get_user_model()
logger = logging.getLogger(__name__)


class MeView(APIView):
    permission_classes = (IsAuthenticated,)

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
    permission_classes = (UserManagementPermission,)
    search_fields = ("email", "display_name")
    ordering_fields = ("email", "display_name", "created_at")
    filterset_fields = ("is_active",)

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .for_user(self.request.user)
            .prefetch_related("role_scopes", "assignments__unit", "student_profile")
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
                if user.role == Role.HOD:
                    RoleScope.objects.bulk_create(
                        [
                            RoleScope(user=user, department_id=department_id)
                            for department_id in values.get("department_ids", [])
                        ]
                    )
                record_audit(
                    actor=request.user,
                    action="invited",
                    instance=user,
                    unit=get_object_unit(user),
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

    @extend_schema(request=ChangeRoleSerializer, responses=UserSerializer)
    @action(detail=True, methods=("patch",), url_path="role")
    def role(self, request, pk=None):
        user = self.get_object()
        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        assert_role_assignment(request.user, values["role"], target=user)

        authentication._ensure_firebase()
        authentication.verify_revoked_token(request)

        before = {
            "role": user.role,
            "department_ids": [
                str(value)
                for value in user.role_scopes.values_list("department_id", flat=True)
            ],
        }
        with transaction.atomic():
            RoleAssignment.objects.filter(user=user).delete()
            if values["role"]:
                RoleAssignment.objects.create(
                    user=user,
                    role=values["role"],
                    unit_id=values.get("unit_id"),
                    granted_by=request.user,
                )
            RoleScope.objects.filter(user=user).delete()
            user.clear_role_cache()
            if values["role"] == Role.HOD:
                RoleScope.objects.bulk_create(
                    [
                        RoleScope(user=user, department_id=department_id)
                        for department_id in values.get("department_ids", [])
                    ]
                )
            after = {
                "role": user.role,
                "department_ids": [
                    str(value) for value in values.get("department_ids", [])
                ],
            }
            record_audit(
                actor=request.user,
                action="role_changed",
                instance=user,
                unit=get_object_unit(user),
                before=before,
                after=after,
            )
        return Response(UserSerializer(user).data)
