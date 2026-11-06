from django.db import IntegrityError, transaction
from django.db.models import Count, Max
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.academics.models import Course
from apps.accounts.roles import ADMIN_ROLES, Role
from apps.enrollment.models import CourseAccess
from apps.people.models import Student
from common.audit import get_object_unit, record_audit
from common.scoping import ScopedViewSetMixin

from .models import Assessment, Grade, Submission
from .permissions import AssessmentPermission, GradebookPermission
from .serializers import (
    AssessmentSerializer,
    GradebookResponseSerializer,
    GradeReviewSerializer,
    GradeSerializer,
    SubmissionSerializer,
)
from .services import record_grade_revision, transition_grade


class DuplicateGrade(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A grade already exists for this submission."
    default_code = "duplicate_grade"


def may_manage_assessment(user, assessment):
    if user.role in ADMIN_ROLES:
        return True
    if user.role == Role.HOD:
        return assessment.course.department.role_scopes.filter(user=user).exists()
    if user.role == Role.TEACHER:
        return bool(
            assessment.course.created_by_id == user.id
            or (
                assessment.class_group_id
                and assessment.class_group.teacher_id == user.id
            )
        )
    return False


class AssessmentViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Assessment.objects.select_related(
        "course__department", "class_group__teacher", "created_by"
    ).annotate(submission_count=Count("submissions", distinct=True))
    serializer_class = AssessmentSerializer
    permission_classes = (AssessmentPermission,)
    search_fields = ("title", "instructions", "course__title")
    ordering_fields = ("title", "due_at", "created_at")
    filterset_fields = ("course", "class_group", "kind", "status")

    def perform_create(self, serializer):
        course = serializer.validated_data["course"]
        group = serializer.validated_data.get("class_group")
        if group and group.teacher_id == self.request.user.id:
            permitted = self.request.user.role == Role.TEACHER
        else:
            permitted = may_manage_assessment(
                self.request.user,
                Assessment(course=course, class_group=group),
            )
        if not permitted:
            raise PermissionDenied("You may not create assessments for this course.")
        with transaction.atomic():
            assessment = serializer.save(created_by=self.request.user)
            record_audit(
                actor=self.request.user,
                action="assessment_created",
                instance=assessment,
                unit=get_object_unit(assessment),
                after=self.get_serializer(assessment).data,
            )

    def perform_update(self, serializer):
        assessment = serializer.instance
        if not may_manage_assessment(self.request.user, assessment):
            raise PermissionDenied("You may not manage this assessment.")
        with transaction.atomic():
            assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
            candidate = Assessment(
                course=serializer.validated_data.get("course", assessment.course),
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
            record_audit(
                actor=self.request.user,
                action="assessment_updated",
                instance=assessment,
                unit=get_object_unit(assessment),
                before=before,
                after=self.get_serializer(assessment).data,
            )

    def perform_destroy(self, instance):
        if not may_manage_assessment(self.request.user, instance):
            raise PermissionDenied("You may not close this assessment.")
        with transaction.atomic():
            instance.status = Assessment.Status.CLOSED
            instance.save(update_fields=("status", "updated_at"))
            record_audit(
                actor=self.request.user,
                action="assessment_archived",
                instance=instance,
                unit=get_object_unit(instance),
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
            assessment.status = Assessment.Status.PUBLISHED
            assessment.save(update_fields=("status", "updated_at"))
            record_audit(
                actor=request.user,
                action="assessment_published",
                instance=assessment,
                unit=get_object_unit(assessment),
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
            assessment.status = Assessment.Status.CLOSED
            assessment.save(update_fields=("status", "updated_at"))
            record_audit(
                actor=request.user,
                action="assessment_closed",
                instance=assessment,
                unit=get_object_unit(assessment),
                after={"status": assessment.status},
            )
        return Response(self.get_serializer(assessment).data)


class SubmissionViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Submission.objects.select_related(
        "assessment__course__department",
        "assessment__class_group__teacher",
        "student",
        "file",
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
        "assessment__title",
    )

    def perform_create(self, serializer):
        try:
            student = Student.objects.get(user=self.request.user, is_active=True)
        except Student.DoesNotExist as exc:
            raise PermissionDenied("An active student profile is required.") from exc
        assessment = serializer.validated_data["assessment"]
        if not CourseAccess.objects.filter(
            student=student, course=assessment.course, is_active=True
        ).exists():
            raise PermissionDenied("You do not have active access to this course.")
        if assessment.status != Assessment.Status.PUBLISHED or (
            assessment.due_at and assessment.due_at < timezone.now()
        ):
            raise ValidationError(
                {"assessment": "This assessment is not accepting submissions."}
            )
        with transaction.atomic():
            assessment = Assessment.objects.select_for_update().get(pk=assessment.pk)
            access = CourseAccess.objects.select_for_update().filter(
                student=student, course=assessment.course, is_active=True
            )
            if not access.exists():
                raise PermissionDenied("You do not have active access to this course.")
            if assessment.status != Assessment.Status.PUBLISHED or (
                assessment.due_at and assessment.due_at < timezone.now()
            ):
                raise ValidationError(
                    {"assessment": "This assessment is not accepting submissions."}
                )
            latest = (
                Submission.objects.filter(
                    assessment=assessment, student=student
                ).aggregate(attempt=Max("attempt_number"))["attempt"]
                or 0
            )
            serializer.validated_data["assessment"] = assessment
            try:
                submission = serializer.save(student=student, attempt_number=latest + 1)
            except IntegrityError as exc:
                raise ValidationError(
                    {"submission": "A concurrent submission was received; retry."}
                ) from exc
            record_audit(
                actor=self.request.user,
                action="assessment_submitted",
                instance=submission,
                unit=get_object_unit(submission),
                after={
                    "assessment_id": str(assessment.id),
                    "student_id": str(student.id),
                    "attempt_number": submission.attempt_number,
                    "file_id": str(submission.file_id),
                },
            )


class GradeViewSet(ScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Grade.objects.select_related(
        "submission__assessment__course__department",
        "submission__assessment__class_group__teacher",
        "submission__student",
        "graded_by",
        "approved_by",
    ).all()
    serializer_class = GradeSerializer
    permission_classes = (AssessmentPermission,)
    http_method_names = ("get", "post", "put", "patch", "head", "options")
    filterset_fields = ("submission__assessment", "submission__student", "status")
    ordering_fields = ("updated_at", "score")
    search_fields = (
        "submission__student__registration_number",
        "submission__student__first_name",
        "submission__student__last_name",
        "submission__assessment__title",
    )

    def perform_create(self, serializer):
        submission = serializer.validated_data["submission"]
        if not may_manage_assessment(self.request.user, submission.assessment):
            raise PermissionDenied("You may not grade this submission.")
        with transaction.atomic():
            try:
                grade = serializer.save(graded_by=self.request.user)
            except IntegrityError as exc:
                raise DuplicateGrade() from exc
            record_grade_revision(grade=grade, actor=self.request.user)
            record_audit(
                actor=self.request.user,
                action="grade_created",
                instance=grade,
                unit=get_object_unit(grade),
                after={"score": str(grade.score), "status": grade.status},
            )

    def perform_update(self, serializer):
        grade = serializer.instance
        if not may_manage_assessment(self.request.user, grade.submission.assessment):
            raise PermissionDenied("You may not edit this grade.")
        with transaction.atomic():
            grade = (
                Grade.objects.select_for_update()
                .select_related("submission__assessment__course")
                .get(pk=grade.pk)
            )
            if grade.status not in {Grade.Status.DRAFT, Grade.Status.REJECTED}:
                raise ValidationError(
                    {"status": "Only draft or returned grades can be edited."}
                )
            before = {"score": str(grade.score), "status": grade.status}
            serializer.instance = grade
            grade = serializer.save(status=Grade.Status.DRAFT, review_note="")
            grade.revision += 1
            grade.save(update_fields=("revision", "updated_at"))
            record_grade_revision(grade=grade, actor=self.request.user)
            record_audit(
                actor=self.request.user,
                action="grade_updated",
                instance=grade,
                unit=get_object_unit(grade),
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
        if not may_manage_assessment(request.user, grade.submission.assessment):
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

    @staticmethod
    def _may_review(user, grade):
        if user.role in ADMIN_ROLES:
            return True
        if user.role == Role.HOD:
            return grade.submission.assessment.course.department.role_scopes.filter(
                user=user
            ).exists()
        return False


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
        if (
            request.user.role == Role.STUDENT
            and not CourseAccess.objects.filter(
                student__user=request.user, course=course, is_active=True
            ).exists()
        ):
            raise PermissionDenied("You do not have access to this course.")
        if (
            request.user.role == Role.TEACHER
            and course.created_by_id != request.user.id
        ):
            raise PermissionDenied("You may not view this course gradebook.")

        assessments = Assessment.objects.filter(course=course).exclude(
            status=Assessment.Status.DRAFT
        )
        if request.user.role == Role.STUDENT:
            assessments = assessments.filter(status=Assessment.Status.PUBLISHED)
        student_query = Student.objects.filter(
            course_access__course=course, course_access__is_active=True
        ).distinct()
        if request.user.role == Role.STUDENT:
            student_query = student_query.filter(user=request.user)
        elif request.user.role == Role.HOD:
            student_query = student_query.filter(
                department__role_scopes__user=request.user
            ).distinct()
        grade_query = Grade.objects.filter(
            submission__assessment__in=assessments
        ).select_related("submission", "submission__assessment")
        if request.user.role == Role.STUDENT:
            grade_query = grade_query.filter(
                submission__student__user=request.user,
                status=Grade.Status.PUBLISHED,
            )
        grades_by_student = {}
        for grade in grade_query.order_by(
            "submission__student_id",
            "submission__assessment_id",
            "submission__attempt_number",
        ):
            grades_by_student.setdefault(str(grade.submission.student_id), {})[
                str(grade.submission.assessment_id)
            ] = {
                "grade_id": str(grade.id),
                "score": str(grade.score),
                "status": grade.status,
                "revision": grade.revision,
            }
        assessment_rows = [
            {
                "id": str(item.id),
                "title": item.title,
                "kind": item.kind,
                "maximum_score": str(item.maximum_score),
                "due_at": item.due_at,
            }
            for item in assessments.order_by("due_at", "title")
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
                        "id": str(student.id),
                        "registration_number": student.registration_number,
                        "name": f"{student.first_name} {student.last_name}",
                        "grades": grades_by_student.get(str(student.id), {}),
                    }
                    for student in student_query.order_by("registration_number")
                ],
            }
        )
