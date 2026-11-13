from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Max, Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Course
from apps.academics.permissions import (
    may_manage_course,
    may_manage_course_department,
)
from apps.accounts.roles import ADMIN_ROLES, GLOBAL_READ_ROLES, Role
from apps.enrollment.models import CourseAccess, Enrollment
from apps.people.models import Student
from apps.scheduling.models import ClassGroup
from common.audit import get_object_audit_scope, record_audit
from common.scoping import ScopedViewSetMixin

from .models import (
    Assessment,
    AssessmentAttemptGrant,
    AssessmentTemplate,
    Grade,
    GradeRevision,
    Submission,
)
from .permissions import AssessmentPermission, GradebookPermission
from .serializers import (
    AssessmentAttemptGrantSerializer,
    AssessmentSerializer,
    AssessmentTemplateSerializer,
    AttemptGrantCreateSerializer,
    GradebookResponseSerializer,
    GradeReviewSerializer,
    GradeRevisionSerializer,
    GradeSerializer,
    SubmissionSerializer,
)
from .services import record_grade_revision, transition_grade


class DuplicateGrade(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A grade already exists for this submission."
    default_code = "duplicate_grade"


def may_manage_assessment(user, assessment):
    if assessment.class_group_id and assessment.class_group.status in {
        ClassGroup.Status.COMPLETED,
        ClassGroup.Status.CANCELLED,
    }:
        return False
    course = assessment.course
    if user.has_role_global(*ADMIN_ROLES):
        return True
    if course.department_id in user.department_ids_for_hod():
        return True
    if user.has_role_for_unit(Role.UNIT_MANAGER, course.unit_id):
        return True
    if user.has_role_for_unit(Role.TEACHER, course.unit_id):
        return bool(
            may_manage_course(user, course)
            or (assessment.class_group_id and assessment.class_group.has_teacher(user))
        )
    return False


def may_manage_assessment_template(user, template):
    course = template.course
    if user.has_role_global(*ADMIN_ROLES):
        return True
    if course.department_id in user.department_ids_for_hod():
        return True
    if user.has_role_for_unit(Role.UNIT_MANAGER, course.unit_id):
        return True
    return bool(
        user.has_role_for_unit(Role.TEACHER, course.unit_id)
        and may_manage_course(user, course)
    )


def lock_editable_class_group(class_group_id):
    if not class_group_id:
        return
    class_group = ClassGroup.objects.select_for_update().get(pk=class_group_id)
    if class_group.status in {
        ClassGroup.Status.COMPLETED,
        ClassGroup.Status.CANCELLED,
    }:
        raise ValidationError(
            {"class_group": "Completed or cancelled classes are locked."}
        )


def may_grade_enrollment(user, assessment, enrollment=None, grant=None):
    class_group = assessment.class_group
    locked = class_group and class_group.status in {
        ClassGroup.Status.COMPLETED,
        ClassGroup.Status.CANCELLED,
    }
    if locked:
        if (
            class_group.status != ClassGroup.Status.COMPLETED
            or enrollment is None
            or grant is None
            or grant.assessment_id != assessment.id
            or grant.enrollment_id != enrollment.id
            or grant.valid_until <= timezone.now()
        ):
            return False
        if class_group.teacher_assignments.filter(is_active=True).exists():
            return bool(
                user.has_role_for_unit(Role.TEACHER, assessment.course.unit_id)
                and class_group.has_teacher(user)
            )
        return bool(
            user.has_role_global(*ADMIN_ROLES)
            or assessment.course.department_id in user.department_ids_for_hod()
            or user.has_role_for_unit(Role.UNIT_MANAGER, assessment.course.unit_id)
        )
    course = assessment.course
    if user.has_role_global(*ADMIN_ROLES):
        return True
    if not user.has_role_for_unit(Role.TEACHER, course.unit_id):
        return False
    return bool(
        course.teacher_assignments.filter(
            teacher=user, can_edit_content=True, is_active=True
        ).exists()
        or (assessment.class_group_id and assessment.class_group.has_teacher(user))
    )


def active_attempt_grant(assessment, enrollment, *, for_update=False):
    grants = AssessmentAttemptGrant.objects.filter(
        assessment=assessment,
        enrollment=enrollment,
        used_at__isnull=True,
        valid_until__gt=timezone.now(),
    ).order_by("created_at")
    if for_update:
        grants = grants.select_for_update()
    return grants.first()


def consume_attempt_grant(*, grant, actor, used_for):
    grant.used_at = timezone.now()
    grant.used_by = actor
    grant.used_for = used_for
    grant.save(update_fields=("used_at", "used_by", "used_for", "updated_at"))
    unit, group_level = get_object_audit_scope(grant)
    record_audit(
        actor=actor,
        action="assessment_attempt_grant_used",
        obj=grant,
        unit=unit,
        group_level=group_level,
        after={"used_for": used_for, "enrollment_id": str(grant.enrollment_id)},
    )


def grade_attempt_grant(grade, *, for_update=False):
    latest = (
        GradeRevision.objects.filter(grade=grade)
        .select_related("attempt_grant")
        .order_by("-revision")
        .first()
    )
    grant = latest.attempt_grant if latest else None
    if (
        grant
        and grant.valid_until > timezone.now()
        and grant.assessment_id == grade.assessment_id
        and grant.enrollment_id == grade.enrollment_id
    ):
        return grant
    return active_attempt_grant(
        grade.assessment, grade.enrollment, for_update=for_update
    )


class AssessmentTemplateViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = AssessmentTemplate.objects.select_related(
        "course__department", "created_by"
    )
    serializer_class = AssessmentTemplateSerializer
    permission_classes = (AssessmentPermission,)
    search_fields = ("title", "instructions", "course__title")
    ordering_fields = ("title", "created_at")
    filterset_fields = ("course", "kind")
    http_method_names = ("get", "post", "put", "patch", "head", "options")

    def perform_create(self, serializer):
        template = AssessmentTemplate(course=serializer.validated_data["course"])
        if not may_manage_assessment_template(self.request.user, template):
            raise PermissionDenied("You may not create templates for this course.")
        with transaction.atomic():
            template = serializer.save(created_by=self.request.user)
            unit, group_level = get_object_audit_scope(template)
            record_audit(
                actor=self.request.user,
                action="assessment_template_created",
                obj=template,
                unit=unit,
                group_level=group_level,
                after=self.get_serializer(template).data,
            )

    def perform_update(self, serializer):
        template = serializer.instance
        if not may_manage_assessment_template(self.request.user, template):
            raise PermissionDenied("You may not manage this assessment template.")
        with transaction.atomic():
            template = AssessmentTemplate.objects.select_for_update().get(
                pk=template.pk
            )
            if template.instances.filter(
                Q(submissions__isnull=False) | Q(grades__isnull=False)
            ).exists():
                raise ValidationError(
                    {
                        "template": "Templates with submissions or grades cannot be changed."
                    }
                )
            before = self.get_serializer(template).data
            serializer.instance = template
            template = serializer.save()
            unit, group_level = get_object_audit_scope(template)
            record_audit(
                actor=self.request.user,
                action="assessment_template_updated",
                obj=template,
                unit=unit,
                group_level=group_level,
                before=before,
                after=self.get_serializer(template).data,
            )


class AssessmentViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Assessment.objects.select_related(
        "template__course__department", "template__created_by"
    ).annotate(submission_count=Count("submissions", distinct=True))
    serializer_class = AssessmentSerializer
    permission_classes = (AssessmentPermission,)
    search_fields = (
        "template__title",
        "template__instructions",
        "template__course__title",
    )
    ordering_fields = ("template__title", "due_at", "created_at")
    filterset_fields = {  # noqa: RUF012
        "template__course": ("exact",),
        "class_group": ("exact",),
        "template__kind": ("exact",),
        "status": ("exact",),
    }

    def perform_create(self, serializer):
        template = serializer.validated_data["template"]
        group = serializer.validated_data.get("class_group")
        if not may_manage_assessment(
            self.request.user, Assessment(template=template, class_group=group)
        ):
            raise PermissionDenied("You may not create assessments from this template.")
        with transaction.atomic():
            lock_editable_class_group(group.pk if group else None)
            assessment = serializer.save()
            unit, group_level = get_object_audit_scope(assessment)
            record_audit(
                actor=self.request.user,
                action="assessment_created",
                obj=assessment,
                unit=unit,
                group_level=group_level,
                after=self.get_serializer(assessment).data,
            )

    def perform_update(self, serializer):
        assessment = serializer.instance
        if not may_manage_assessment(self.request.user, assessment):
            raise PermissionDenied("You may not manage this assessment.")
        with transaction.atomic():
            assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
            lock_editable_class_group(assessment.class_group_id)
            candidate = Assessment(
                template=serializer.validated_data.get("template", assessment.template),
                class_group=serializer.validated_data.get(
                    "class_group", assessment.class_group
                ),
            )
            if not may_manage_assessment(self.request.user, candidate):
                raise PermissionDenied("You may not manage the updated assessment.")
            if assessment.status != Assessment.Status.DRAFT:
                raise ValidationError(
                    {"status": "Only draft assessments can be edited."}
                )
            before = self.get_serializer(assessment).data
            serializer.instance = assessment
            assessment = serializer.save()
            unit, group_level = get_object_audit_scope(assessment)
            record_audit(
                actor=self.request.user,
                action="assessment_updated",
                obj=assessment,
                unit=unit,
                group_level=group_level,
                before=before,
                after=self.get_serializer(assessment).data,
            )

    def perform_destroy(self, instance):
        if not may_manage_assessment(self.request.user, instance):
            raise PermissionDenied("You may not close this assessment.")
        with transaction.atomic():
            lock_editable_class_group(instance.class_group_id)
            instance.status = Assessment.Status.CLOSED
            instance.save(update_fields=("status", "updated_at"))
            unit, group_level = get_object_audit_scope(instance)
            record_audit(
                actor=self.request.user,
                action="assessment_archived",
                obj=instance,
                unit=unit,
                group_level=group_level,
                after={"status": instance.status},
            )

    @extend_schema(request=None, responses=AssessmentSerializer)
    @action(detail=True, methods=("post",))
    def publish(self, request, pk=None):
        assessment = self.get_object()
        if not may_manage_assessment(request.user, assessment):
            raise PermissionDenied("You may not publish this assessment.")
        if assessment.status != Assessment.Status.DRAFT:
            raise ValidationError(
                {"status": "Only draft assessments can be published."}
            )
        with transaction.atomic():
            lock_editable_class_group(assessment.class_group_id)
            assessment.status = Assessment.Status.PUBLISHED
            assessment.save(update_fields=("status", "updated_at"))
            unit, group_level = get_object_audit_scope(assessment)
            record_audit(
                actor=request.user,
                action="assessment_published",
                obj=assessment,
                unit=unit,
                group_level=group_level,
                after={"status": assessment.status},
            )
        return Response(self.get_serializer(assessment).data)

    @extend_schema(request=None, responses=AssessmentSerializer)
    @action(detail=True, methods=("post",))
    def close(self, request, pk=None):
        assessment = self.get_object()
        if not may_manage_assessment(request.user, assessment):
            raise PermissionDenied("You may not close this assessment.")
        if assessment.status != Assessment.Status.PUBLISHED:
            raise ValidationError(
                {"status": "Only published assessments can be closed."}
            )
        with transaction.atomic():
            lock_editable_class_group(assessment.class_group_id)
            assessment.status = Assessment.Status.CLOSED
            assessment.save(update_fields=("status", "updated_at"))
            unit, group_level = get_object_audit_scope(assessment)
            record_audit(
                actor=request.user,
                action="assessment_closed",
                obj=assessment,
                unit=unit,
                group_level=group_level,
                after={"status": assessment.status},
            )
        return Response(self.get_serializer(assessment).data)

    @extend_schema(
        request=AttemptGrantCreateSerializer,
        responses={201: AssessmentAttemptGrantSerializer},
    )
    @action(detail=True, methods=("post",), url_path="re-open")
    def reopen(self, request, pk=None):
        assessment = self.get_object()
        serializer = AttemptGrantCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        enrollment = serializer.validated_data["enrollment"]
        locked = assessment.class_group_id and assessment.class_group.status in {
            ClassGroup.Status.COMPLETED,
            ClassGroup.Status.CANCELLED,
        }
        may_grant = request.user.has_role_global(*ADMIN_ROLES)
        if not may_grant:
            may_grant = bool(
                assessment.course.department_id in request.user.department_ids_for_hod()
                or request.user.has_role_for_unit(
                    Role.UNIT_MANAGER, assessment.course.unit_id
                )
                or (
                    not locked
                    and request.user.has_role_for_unit(
                        Role.TEACHER, assessment.course.unit_id
                    )
                    and (
                        may_manage_course(request.user, assessment.course)
                        or (
                            assessment.class_group_id
                            and assessment.class_group.has_teacher(request.user)
                        )
                    )
                )
            )
        if not may_grant:
            raise PermissionDenied("You may not grant an attempt for this assessment.")
        if (
            assessment.class_group_id
            and assessment.class_group.status == ClassGroup.Status.CANCELLED
        ):
            raise ValidationError(
                {"class_group": "Cancelled classes cannot be re-opened."}
            )
        if assessment.status not in {
            Assessment.Status.PUBLISHED,
            Assessment.Status.CLOSED,
        }:
            raise ValidationError(
                {"assessment": "Only published or closed assessments can be re-opened."}
            )
        if enrollment.course_id != assessment.course.id or (
            assessment.class_group_id
            and enrollment.class_group_id != assessment.class_group_id
        ):
            raise ValidationError(
                {"enrollment": "The enrollment does not belong to this assessment."}
            )
        if enrollment.status not in {
            Enrollment.Status.ACTIVE,
            Enrollment.Status.COMPLETED,
        }:
            raise ValidationError(
                {"enrollment": "Only active or completed enrollments can be re-opened."}
            )
        valid_until = serializer.validated_data.get(
            "valid_until", timezone.now() + timedelta(days=7)
        )
        if valid_until <= timezone.now():
            raise ValidationError(
                {"valid_until": "The grant must expire in the future."}
            )
        with transaction.atomic():
            locked_assessment = Assessment.objects.select_for_update().get(
                pk=assessment.pk
            )
            grant = AssessmentAttemptGrant.objects.create(
                assessment=locked_assessment,
                enrollment=enrollment,
                granted_by=request.user,
                reason=serializer.validated_data["reason"],
                valid_until=valid_until,
            )
            unit, group_level = get_object_audit_scope(grant)
            record_audit(
                actor=request.user,
                action="assessment_attempt_grant_created",
                obj=grant,
                unit=unit,
                group_level=group_level,
                after={
                    "assessment_id": str(assessment.id),
                    "enrollment_id": str(enrollment.id),
                    "reason": grant.reason,
                    "valid_until": grant.valid_until,
                },
            )
        return Response(
            AssessmentAttemptGrantSerializer(grant).data,
            status=status.HTTP_201_CREATED,
        )


class SubmissionViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Submission.objects.select_related(
        "assessment__template__course__department", "student", "file"
    ).all()
    serializer_class = SubmissionSerializer
    permission_classes = (AssessmentPermission,)
    http_method_names = ("get", "post", "head", "options")
    filterset_fields = ("assessment", "student")
    ordering_fields = ("submitted_at", "attempt_number")
    search_fields = (
        "student__registration_number",
        "student__first_name",
        "student__last_name",
        "assessment__template__title",
    )

    def perform_create(self, serializer):
        try:
            student = Student.objects.get(user=self.request.user, is_active=True)
        except Student.DoesNotExist as exc:
            raise PermissionDenied("An active student profile is required.") from exc
        assessment = serializer.validated_data["assessment"]
        with transaction.atomic():
            assessment = (
                Assessment.objects.select_for_update(of=("self",))
                .select_related("template__course", "class_group")
                .get(pk=assessment.pk)
            )
            now = timezone.now()
            if assessment.class_group_id:
                class_group = ClassGroup.objects.select_for_update().get(
                    pk=assessment.class_group_id
                )
                if class_group.status == ClassGroup.Status.CANCELLED:
                    raise ValidationError(
                        {"assessment": "Cancelled classes cannot accept submissions."}
                    )
            enrollment = (
                Enrollment.objects.select_for_update()
                .filter(student=student, course=assessment.course)
                .first()
            )
            if enrollment is None or (
                assessment.class_group_id
                and enrollment.class_group_id != assessment.class_group_id
            ):
                raise PermissionDenied("An enrollment for this class is required.")
            if enrollment.status not in {
                Enrollment.Status.ACTIVE,
                Enrollment.Status.COMPLETED,
            }:
                raise PermissionDenied("This enrollment cannot submit work.")
            if assessment.status not in {
                Assessment.Status.PUBLISHED,
                Assessment.Status.CLOSED,
            }:
                raise ValidationError(
                    {"assessment": "This assessment is not open for submissions."}
                )
            latest = (
                Submission.objects.filter(
                    assessment=assessment, student=student
                ).aggregate(attempt=Max("attempt_number"))["attempt"]
                or 0
            )
            used_submission_grants = AssessmentAttemptGrant.objects.filter(
                assessment=assessment,
                enrollment=enrollment,
                used_for=Grade.Source.SUBMISSION,
            ).count()
            attempt_limit_requires_grant = (
                latest + 1 > assessment.max_attempts + used_submission_grants
            )
            late = bool(assessment.due_at and now > assessment.due_at)
            beyond_late_window = bool(
                late and (assessment.late_until is None or now > assessment.late_until)
            )
            locked = bool(
                assessment.class_group_id
                and class_group.status == ClassGroup.Status.COMPLETED
            )
            requires_grant = bool(
                assessment.status == Assessment.Status.CLOSED
                or beyond_late_window
                or attempt_limit_requires_grant
                or locked
                or enrollment.status == Enrollment.Status.COMPLETED
            )
            grant = (
                active_attempt_grant(assessment, enrollment, for_update=True)
                if requires_grant
                else None
            )
            if requires_grant and grant is None:
                raise ValidationError(
                    {
                        "assessment": "A valid, unused attempt grant is required for this submission."
                    }
                )
            if (
                enrollment.status == Enrollment.Status.ACTIVE
                and not CourseAccess.objects.select_for_update()
                .filter(student=student, course=assessment.course, is_active=True)
                .exists()
            ):
                raise PermissionDenied("You do not have active access to this course.")
            if (
                latest + 1 > assessment.max_attempts + used_submission_grants
                and grant is None
            ):
                raise ValidationError(
                    {"assessment": "The maximum number of attempts has been reached."}
                )
            serializer.validated_data["assessment"] = assessment
            try:
                submission = serializer.save(
                    student=student,
                    attempt_number=latest + 1,
                    is_late=late,
                )
            except IntegrityError as exc:
                raise ValidationError(
                    {"submission": "A concurrent submission was received; retry."}
                ) from exc
            if grant:
                consume_attempt_grant(
                    grant=grant,
                    actor=self.request.user,
                    used_for=Grade.Source.SUBMISSION,
                )
            grade = (
                Grade.objects.select_for_update()
                .filter(assessment=assessment, enrollment=enrollment)
                .first()
            )
            if grade and grade.status in {
                Grade.Status.PENDING_APPROVAL,
                Grade.Status.APPROVED,
            }:
                raise ValidationError(
                    {"status": "Edit the current draft instead of creating another."}
                )
            if grade is None:
                grade = Grade.objects.create(
                    assessment=assessment,
                    enrollment=enrollment,
                    submission=submission,
                    source=Grade.Source.SUBMISSION,
                    status=Grade.Status.DRAFT,
                )
            else:
                grade.submission = submission
                grade.source = Grade.Source.SUBMISSION
                grade.score = None
                grade.feedback = ""
                grade.status = Grade.Status.DRAFT
                grade.revision += 1
                grade.graded_by = None
                grade.approved_by = None
                grade.approved_at = None
                grade.published_by = None
                grade.published_at = None
                grade.review_note = ""
                grade.save(
                    update_fields=(
                        "submission",
                        "source",
                        "score",
                        "feedback",
                        "status",
                        "revision",
                        "graded_by",
                        "approved_by",
                        "approved_at",
                        "published_by",
                        "published_at",
                        "review_note",
                        "updated_at",
                    )
                )
            record_grade_revision(
                grade=grade,
                actor=self.request.user,
                change_note=f"Submission attempt {submission.attempt_number}",
                attempt_grant=grant,
            )
            unit, group_level = get_object_audit_scope(submission)
            record_audit(
                actor=self.request.user,
                action="assessment_submitted",
                obj=submission,
                unit=unit,
                group_level=group_level,
                after={
                    "assessment_id": str(assessment.id),
                    "student_id": str(student.id),
                    "attempt_number": submission.attempt_number,
                    "file_id": str(submission.file_id),
                },
            )


class GradeViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Grade.objects.select_related(
        "assessment__template__course__department",
        "assessment__class_group",
        "enrollment__student",
        "enrollment__class_group",
        "submission",
        "official_revision",
        "graded_by",
        "approved_by",
        "published_by",
    ).all()
    serializer_class = GradeSerializer
    permission_classes = (AssessmentPermission,)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    filterset_fields = ("assessment", "enrollment", "status")
    ordering_fields = ("updated_at", "score")
    search_fields = (
        "enrollment__student__registration_number",
        "enrollment__student__first_name",
        "enrollment__student__last_name",
        "assessment__template__title",
    )

    def perform_create(self, serializer):
        values = serializer.validated_data
        assessment = values["assessment"]
        enrollment = values["enrollment"]
        if values.get("score") is None:
            raise ValidationError({"score": "A staff-recorded grade requires a score."})
        if assessment.template.course_id != enrollment.course_id or (
            assessment.class_group_id
            and assessment.class_group_id != enrollment.class_group_id
        ):
            raise ValidationError(
                {"enrollment": "The enrollment does not belong to this assessment."}
            )
        if enrollment.status not in {
            Enrollment.Status.ACTIVE,
            Enrollment.Status.COMPLETED,
        }:
            raise ValidationError(
                {"enrollment": "Only active or completed enrollments can be graded."}
            )
        with transaction.atomic():
            assessment = (
                Assessment.objects.select_for_update(of=("self",))
                .select_related("template__course", "class_group")
                .get(pk=assessment.pk)
            )
            enrollment = Enrollment.objects.select_for_update().get(pk=enrollment.pk)
            if assessment.class_group_id:
                class_group = ClassGroup.objects.select_for_update().get(
                    pk=assessment.class_group_id
                )
                if class_group.status == ClassGroup.Status.CANCELLED:
                    raise ValidationError(
                        {"class_group": "Grades cannot be added to a cancelled class."}
                    )
            grade = (
                Grade.objects.select_for_update()
                .filter(assessment=assessment, enrollment=enrollment)
                .first()
            )
            grant = (
                grade_attempt_grant(grade, for_update=True)
                if grade
                else active_attempt_grant(assessment, enrollment, for_update=True)
            )
            locked = bool(
                assessment.class_group_id
                and class_group.status == ClassGroup.Status.COMPLETED
            )
            if not locked:
                grant = None
            if locked and grant is None:
                raise ValidationError(
                    {"grant": "A valid grant is required to grade after class lock."}
                )
            if not may_grade_enrollment(
                self.request.user, assessment, enrollment, grant
            ):
                raise PermissionDenied("You may not grade this enrollment.")
            if grant and grant.used_at is None:
                consume_attempt_grant(
                    grant=grant,
                    actor=self.request.user,
                    used_for=Grade.Source.STAFF_RECORDED,
                )
            change_note = values.pop("change_note", "").strip()
            if not change_note:
                raise ValidationError(
                    {"change_note": "Provide a reason for the staff-recorded mark."}
                )
            if grade is None:
                grade = Grade.objects.create(
                    assessment=assessment,
                    enrollment=enrollment,
                    submission=None,
                    source=Grade.Source.STAFF_RECORDED,
                    score=values["score"],
                    feedback=values.get("feedback", ""),
                    status=Grade.Status.DRAFT,
                    graded_by=self.request.user,
                )
            else:
                grade.submission = None
                grade.source = Grade.Source.STAFF_RECORDED
                grade.score = values["score"]
                grade.feedback = values.get("feedback", "")
                grade.status = Grade.Status.DRAFT
                grade.revision += 1
                grade.graded_by = self.request.user
                grade.approved_by = None
                grade.approved_at = None
                grade.published_by = None
                grade.published_at = None
                grade.review_note = ""
                grade.save(
                    update_fields=(
                        "submission",
                        "source",
                        "score",
                        "feedback",
                        "status",
                        "revision",
                        "graded_by",
                        "approved_by",
                        "approved_at",
                        "published_by",
                        "published_at",
                        "review_note",
                        "updated_at",
                    )
                )
            record_grade_revision(
                grade=grade,
                actor=self.request.user,
                change_note=change_note,
                attempt_grant=grant,
            )
            serializer.instance = grade
            unit, group_level = get_object_audit_scope(grade)
            record_audit(
                actor=self.request.user,
                action="grade_created",
                obj=grade,
                unit=unit,
                group_level=group_level,
                after={
                    "assessment_id": str(assessment.id),
                    "enrollment_id": str(enrollment.id),
                    "score": str(grade.score),
                    "status": grade.status,
                    "source": grade.source,
                },
            )

    def perform_update(self, serializer):
        grade = serializer.instance
        with transaction.atomic():
            grade = (
                Grade.objects.select_for_update(of=("self",))
                .select_related(
                    "assessment__template__course",
                    "assessment__class_group",
                    "enrollment__student",
                )
                .get(pk=grade.pk)
            )
            class_group = None
            if grade.assessment.class_group_id:
                class_group = ClassGroup.objects.select_for_update().get(
                    pk=grade.assessment.class_group_id
                )
            grant = grade_attempt_grant(grade, for_update=True)
            locked = bool(
                class_group and class_group.status == ClassGroup.Status.COMPLETED
            )
            if not locked:
                grant = None
            if locked and grant is None:
                raise ValidationError(
                    {"grant": "A valid grant is required to grade after class lock."}
                )
            if class_group and class_group.status == ClassGroup.Status.CANCELLED:
                raise ValidationError(
                    {"class_group": "Grades cannot change in a cancelled class."}
                )
            if not may_grade_enrollment(
                self.request.user, grade.assessment, grade.enrollment, grant
            ):
                raise PermissionDenied("You may not edit this grade.")
            if grade.status not in {
                Grade.Status.DRAFT,
                Grade.Status.REJECTED,
                Grade.Status.PUBLISHED,
            }:
                raise ValidationError(
                    {
                        "status": "Only drafts, returned grades, or published grades can be revised."
                    }
                )
            before = {"score": str(grade.score), "status": grade.status}
            serializer.instance = grade
            change_note = serializer.validated_data.get("change_note", "")
            grade = serializer.save(
                status=Grade.Status.DRAFT,
                review_note="",
                graded_by=self.request.user,
                approved_by=None,
                approved_at=None,
                published_by=None,
                published_at=None,
            )
            grade.revision += 1
            grade.save(update_fields=("revision", "updated_at"))
            if grant and grant.used_at is None:
                consume_attempt_grant(
                    grant=grant,
                    actor=self.request.user,
                    used_for=Grade.Source.STAFF_RECORDED,
                )
            record_grade_revision(
                grade=grade,
                actor=self.request.user,
                change_note=change_note,
                attempt_grant=grant,
            )
            unit, group_level = get_object_audit_scope(grade)
            record_audit(
                actor=self.request.user,
                action="grade_updated",
                obj=grade,
                unit=unit,
                group_level=group_level,
                before=before,
                after={
                    "score": str(grade.score),
                    "status": grade.status,
                    "revision": grade.revision,
                },
            )

    @extend_schema(request=None, responses=GradeSerializer)
    @action(detail=True, methods=("post",), url_path="submit-for-approval")
    def submit_for_approval(self, request, pk=None):
        grade = self.get_object()
        grant = grade_attempt_grant(grade)
        if not may_grade_enrollment(
            request.user, grade.assessment, grade.enrollment, grant
        ):
            raise PermissionDenied("You may not submit this grade for approval.")
        grade = transition_grade(grade_id=grade.pk, actor=request.user, action="submit")
        return Response(self.get_serializer(grade).data)

    @extend_schema(request=None, responses=GradeSerializer)
    @action(detail=True, methods=("post",))
    def approve(self, request, pk=None):
        grade = self.get_object()
        if not self._may_review(request.user, grade):
            raise PermissionDenied(
                "Only an administrator or the scoped HOD may approve grades."
            )
        grade = transition_grade(
            grade_id=grade.pk, actor=request.user, action="approve"
        )
        return Response(self.get_serializer(grade).data)

    @extend_schema(request=GradeReviewSerializer, responses=GradeSerializer)
    @action(detail=True, methods=("post",))
    def reject(self, request, pk=None):
        grade = self.get_object()
        if not self._may_review(request.user, grade):
            raise PermissionDenied(
                "Only an administrator or the scoped HOD may return grades."
            )
        grade = transition_grade(
            grade_id=grade.pk,
            actor=request.user,
            action="reject",
            note=request.data.get("note", ""),
        )
        return Response(self.get_serializer(grade).data)

    @extend_schema(request=None, responses=GradeSerializer)
    @action(detail=True, methods=("post",))
    def publish(self, request, pk=None):
        grade = self.get_object()
        if not self._may_review(request.user, grade):
            raise PermissionDenied(
                "Only a scoped HOD, unit manager, or administrator may publish grades."
            )
        grade = transition_grade(
            grade_id=grade.pk, actor=request.user, action="publish"
        )
        return Response(self.get_serializer(grade).data)

    @extend_schema(request=None, responses=GradeSerializer)
    @action(detail=True, methods=("post",), url_path="approve-and-publish")
    def approve_and_publish(self, request, pk=None):
        grade = self.get_object()
        if not self._may_review(request.user, grade):
            raise PermissionDenied(
                "Only a scoped HOD, unit manager, or administrator may approve grades."
            )
        grade = transition_grade(
            grade_id=grade.pk, actor=request.user, action="approve_and_publish"
        )
        return Response(self.get_serializer(grade).data)

    @extend_schema(responses=GradeRevisionSerializer(many=True))
    @action(detail=True, methods=("get",))
    def revisions(self, request, pk=None):
        grade = self.get_object()
        revisions = grade.revisions.select_related(
            "changed_by", "approved_by", "published_by", "attempt_grant"
        ).order_by("revision")
        if request.user.has_role(Role.STUDENT):
            revisions = revisions.filter(pk=grade.official_revision_id)
        page = self.paginate_queryset(revisions)
        if page is not None:
            return self.get_paginated_response(
                GradeRevisionSerializer(page, many=True).data
            )
        return Response(GradeRevisionSerializer(revisions, many=True).data)

    @staticmethod
    def _may_review(user, grade):
        latest = (
            grade.revisions.select_related("attempt_grant")
            .order_by("-revision")
            .first()
        )
        grantor_id = (
            latest.attempt_grant.granted_by_id
            if latest and latest.attempt_grant_id
            else None
        )
        if user.id in {grade.graded_by_id, grantor_id}:
            return False
        return bool(
            user.has_role_global(*ADMIN_ROLES)
            or grade.assessment.course.department_id in user.department_ids_for_hod()
            or user.has_role_for_unit(
                Role.UNIT_MANAGER, grade.assessment.course.unit_id
            )
        )


class AssessmentAttemptGrantViewSet(ScopedViewSetMixin, viewsets.ReadOnlyModelViewSet):
    queryset = AssessmentAttemptGrant.objects.select_related(
        "assessment__template__course__department",
        "enrollment__student",
        "granted_by",
        "used_by",
    )
    serializer_class = AssessmentAttemptGrantSerializer
    permission_classes = (AssessmentPermission,)
    filterset_fields = ("assessment", "enrollment", "used_for")
    ordering_fields = ("created_at", "valid_until", "used_at")
    http_method_names = ("get", "head", "options")


class GradebookView(APIView):
    permission_classes = (GradebookPermission,)

    @extend_schema(
        parameters=[
            OpenApiParameter(
                name="course",
                type=str,
                location=OpenApiParameter.QUERY,
                required=True,
                description="Course UUID",
            )
        ],
        responses=GradebookResponseSerializer,
    )
    def get(self, request):
        course_id = request.query_params.get("course")
        if not course_id:
            raise ValidationError({"course": "Provide a course id."})
        try:
            course = Course.objects.for_user(request.user).get(pk=course_id)
        except (Course.DoesNotExist, ValueError) as exc:
            raise PermissionDenied("You may not view this course gradebook.") from exc

        user = request.user
        student_enrollment = (
            Enrollment.objects.filter(
                student__user=user,
                course=course,
                status__in=(Enrollment.Status.ACTIVE, Enrollment.Status.COMPLETED),
            )
            .select_related("class_group")
            .first()
        )
        student_access = user.has_role(Role.STUDENT) and student_enrollment is not None
        teacher_unit_role = user.has_role_for_unit(Role.TEACHER, course.unit_id)
        teacher_class_access = (
            teacher_unit_role
            and course.class_groups.filter(
                teacher_assignments__teacher=user,
                teacher_assignments__is_active=True,
            ).exists()
        )
        staff_access = (
            user.has_role_global(*GLOBAL_READ_ROLES)
            or may_manage_course_department(user, course.department)
            or (
                teacher_unit_role
                and (may_manage_course(user, course) or teacher_class_access)
            )
        )
        if not staff_access and not student_access:
            raise PermissionDenied("You may not view this course gradebook.")

        assessments = Assessment.objects.filter(template__course=course).exclude(
            status=Assessment.Status.DRAFT
        )
        student_view = student_access and not staff_access
        if student_view:
            assessments = assessments.filter(
                status__in=(Assessment.Status.PUBLISHED, Assessment.Status.CLOSED),
                class_group=student_enrollment.class_group,
            )
        enrollments = Enrollment.objects.filter(
            course=course,
            status__in=(
                Enrollment.Status.ACTIVE,
                Enrollment.Status.COMPLETED,
            ),
        ).select_related("student", "class_group")
        if student_view:
            enrollments = enrollments.filter(student__user=user)
        elif (
            user.has_role(Role.HOD)
            and course.department_id in user.department_ids_for_hod()
            and not user.has_role_for_unit(Role.UNIT_MANAGER, course.unit_id)
            and not teacher_class_access
            and not user.has_role_global(*GLOBAL_READ_ROLES)
        ):
            enrollments = enrollments.filter(
                student__department_id__in=user.department_ids_for_hod()
            ).distinct()
        grade_query = Grade.objects.filter(
            assessment__in=assessments,
            enrollment__course=course,
        ).select_related("enrollment__student", "official_revision")
        if student_view:
            grade_query = grade_query.filter(
                enrollment__student__user=user,
                official_revision__status=Grade.Status.PUBLISHED,
            )
        grades_by_student = {}
        for grade in grade_query.order_by("enrollment__student_id", "assessment_id"):
            grades_by_student.setdefault(str(grade.enrollment.student_id), {})[
                str(grade.assessment_id)
            ] = {
                "grade_id": str(grade.id),
                "score": (
                    str(grade.official_revision.score)
                    if student_view and grade.official_revision.score is not None
                    else str(grade.score)
                    if grade.score is not None
                    else None
                ),
                "official_score": (
                    str(grade.official_revision.score)
                    if grade.official_revision
                    and grade.official_revision.score is not None
                    else None
                ),
                "status": (
                    grade.official_revision.status if student_view else grade.status
                ),
                "revision": (
                    grade.official_revision.revision if student_view else grade.revision
                ),
                "regrade_pending": bool(
                    grade.official_revision_id
                    and grade.status != Grade.Status.PUBLISHED
                ),
            }
        assessment_rows = [
            {
                "id": str(item.id),
                "class_group": str(item.class_group_id)
                if item.class_group_id
                else None,
                "title": item.title,
                "kind": item.kind,
                "maximum_score": str(item.maximum_score),
                "due_at": item.due_at,
                "late_until": item.late_until,
                "max_attempts": item.max_attempts,
            }
            for item in assessments.order_by("due_at", "template__title")
        ]
        return Response(
            {
                "course": {
                    "id": str(course.id),
                    "title": course.title,
                    "code": course.code,
                },
                "assessments": assessment_rows,
                "students": [
                    {
                        "id": str(enrollment.student_id),
                        "enrollment_id": str(enrollment.id),
                        "class_group": (
                            str(enrollment.class_group_id)
                            if enrollment.class_group_id
                            else None
                        ),
                        "registration_number": enrollment.student.registration_number,
                        "name": (
                            f"{enrollment.student.first_name} "
                            f"{enrollment.student.last_name}"
                        ),
                        "grades": grades_by_student.get(str(enrollment.student_id), {}),
                    }
                    for enrollment in enrollments.order_by(
                        "student__registration_number"
                    )
                ],
            }
        )
