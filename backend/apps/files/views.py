from uuid import uuid4

from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from apps.accounts.models import User
from apps.accounts.roles import GLOBAL_READ_ROLES
from common.audit import record_audit
from common.permissions import ReadOnlyRoleWritePermission

from .models import StoredFile
from .policies import UPLOAD_POLICIES
from .serializers import (
    DownloadUrlSerializer,
    StoredFileSerializer,
    UploadRequestSerializer,
    UploadStartedSerializer,
)
from .storage import get_storage_client


class FileStorageViewSet(GenericViewSet):
    queryset = StoredFile.objects.all()
    serializer_class = StoredFileSerializer
    permission_classes = (IsAuthenticated, ReadOnlyRoleWritePermission)

    def get_object(self):
        try:
            stored_file = StoredFile.objects.get(pk=self.kwargs["pk"])
        except StoredFile.DoesNotExist as exc:
            raise NotFound() from exc
        if stored_file.owner_user_id != self.request.user.id:
            raise PermissionDenied()
        return stored_file

    @extend_schema(
        request=UploadRequestSerializer, responses={201: UploadStartedSerializer}
    )
    @action(detail=False, methods=("post",), url_path="uploads")
    def uploads(self, request):
        serializer = UploadRequestSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        values = serializer.validated_data
        stored_file = StoredFile(
            purpose=values["purpose"],
            owner_user=request.user,
            object_key=(f"{values['purpose']}/{timezone.now():%Y/%m}/{uuid4().hex}"),
            original_name=values["filename"],
            content_type=values["content_type"],
            size_bytes=values["size"],
        )
        client = get_storage_client()
        try:
            upload_url = client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": settings.STORAGE_BUCKET,
                    "Key": stored_file.object_key,
                    "ContentType": stored_file.content_type,
                },
                ExpiresIn=300,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ValidationError(
                {"storage": "Could not prepare the upload. Please try again."}
            ) from exc

        with transaction.atomic():
            User.objects.select_for_update().get(pk=request.user.pk)
            used_bytes = (
                StoredFile.objects.filter(
                    owner_user=request.user,
                    status__in=(StoredFile.Status.PENDING, StoredFile.Status.READY),
                ).aggregate(total=Sum("size_bytes"))["total"]
                or 0
            )
            if used_bytes + stored_file.size_bytes > settings.FILE_STORAGE_QUOTA_BYTES:
                raise ValidationError(
                    {"size": "This upload would exceed your storage quota."}
                )
            stored_file.save()
            record_audit(
                actor=request.user,
                action="file_upload_started",
                obj=stored_file,
                unit=None,
                group_level=True,
                after={
                    "purpose": stored_file.purpose,
                    "size_bytes": stored_file.size_bytes,
                },
            )
        return Response(
            {
                "file": StoredFileSerializer(stored_file).data,
                "upload_url": upload_url,
                "headers": {"Content-Type": stored_file.content_type},
            },
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(request=None, responses=StoredFileSerializer)
    @action(detail=True, methods=("post",))
    def complete(self, request, pk=None):
        stored_file = self.get_object()
        if stored_file.status != StoredFile.Status.PENDING:
            raise ValidationError({"status": "This upload is not pending."})
        client = get_storage_client()
        try:
            metadata = client.head_object(
                Bucket=settings.STORAGE_BUCKET,
                Key=stored_file.object_key,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ValidationError(
                {"file": "Uploaded object could not be verified."}
            ) from exc

        policy = UPLOAD_POLICIES[stored_file.purpose]
        valid = (
            metadata.get("ContentLength") == stored_file.size_bytes
            and metadata.get("ContentType") == stored_file.content_type
            and stored_file.size_bytes <= policy["max_bytes"]
        )
        if not valid:
            try:
                client.delete_object(
                    Bucket=settings.STORAGE_BUCKET,
                    Key=stored_file.object_key,
                )
            except (BotoCoreError, ClientError) as exc:
                raise ValidationError(
                    {
                        "file": "Upload verification failed and cleanup could not complete."
                    }
                ) from exc
            stored_file.status = StoredFile.Status.DELETED
            stored_file.save(update_fields=("status", "updated_at"))
            raise ValidationError(
                {"file": "Uploaded object did not pass verification."}
            )

        with transaction.atomic():
            stored_file.status = StoredFile.Status.READY
            stored_file.save(update_fields=("status", "updated_at"))
            record_audit(
                actor=request.user,
                action="file_upload_completed",
                obj=stored_file,
                unit=None,
                group_level=True,
            )
        return Response(StoredFileSerializer(stored_file).data)

    @extend_schema(responses=DownloadUrlSerializer)
    @action(detail=True, methods=("get",), url_path="download-url")
    def download_url(self, request, pk=None):
        stored_file = self._get_stored_file()
        if stored_file.status != StoredFile.Status.READY:
            raise NotFound()
        if not self._may_download(stored_file):
            raise PermissionDenied()
        client = get_storage_client()
        try:
            url = client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": settings.STORAGE_BUCKET,
                    "Key": stored_file.object_key,
                    "ResponseContentDisposition": (
                        f'attachment; filename="{stored_file.original_name}"'
                    ),
                },
                ExpiresIn=300,
            )
        except (BotoCoreError, ClientError) as exc:
            raise ValidationError(
                {"storage": "Could not prepare the download. Please try again."}
            ) from exc
        return Response({"download_url": url, "expires_in": 300})

    def get_permissions(self):
        if getattr(self, "action", None) == "download_url":
            return [AllowAny()]
        return [permission() for permission in self.permission_classes]

    def _get_stored_file(self):
        try:
            return StoredFile.objects.get(pk=self.kwargs["pk"])
        except StoredFile.DoesNotExist as exc:
            raise NotFound() from exc

    def _may_download(self, stored_file):
        from apps.academics.models import Course, Material
        from apps.academics.permissions import may_manage_course

        if stored_file.purpose == StoredFile.Purpose.COVER_IMAGE:
            course_ids = Course.objects.filter(cover_image=stored_file).values("id")
        elif stored_file.purpose == StoredFile.Purpose.MATERIAL:
            user = self.request.user
            materials = Material.objects.filter(file=stored_file).select_related(
                "lesson__unit__module__course__department"
            )
            for material in materials:
                lesson = material.lesson
                unit = lesson.unit
                module = unit.module
                course = module.course
                if (
                    material.is_active
                    and material.is_visible
                    and lesson.is_active
                    and lesson.is_visible
                    and unit.is_active
                    and unit.is_visible
                    and module.is_active
                    and module.is_visible
                    and course.status == Course.Status.PUBLISHED
                    and course.is_active
                ):
                    return True
                if user.is_authenticated and may_manage_course(user, course):
                    return True
            return False
        elif stored_file.purpose == StoredFile.Purpose.SUBMISSION:
            from apps.assessment.models import Submission
            from apps.assessment.views import may_manage_assessment

            submissions = Submission.objects.filter(file=stored_file).select_related(
                "assessment__template__course__department"
            )
            user = self.request.user
            if user.has_role_global(*GLOBAL_READ_ROLES):
                return True
            return any(
                may_manage_assessment(user, item.assessment) for item in submissions
            )
        elif stored_file.purpose == StoredFile.Purpose.PROFILE_PHOTO:
            from apps.people.models import Student
            from apps.people.permissions import may_read_restricted_student

            user = self.request.user
            if not user.is_authenticated:
                return False
            student = Student.objects.filter(photo_file=stored_file).first()
            return bool(
                student and may_read_restricted_student(user=user, student=student)
            )
        else:
            return False

        if Course.objects.filter(
            id__in=course_ids, status=Course.Status.PUBLISHED, is_active=True
        ).exists():
            return True
        user = self.request.user
        if not user.is_authenticated:
            return False
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return True
        courses = Course.objects.filter(id__in=course_ids)
        return any(may_manage_course(user, course) for course in courses)
