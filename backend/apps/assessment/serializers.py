from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from apps.accounts.roles import Role
from apps.enrollment.models import Enrollment
from apps.files.models import StoredFile

from .models import (
    Assessment,
    AssessmentAttemptGrant,
    AssessmentTemplate,
    Grade,
    GradeRevision,
    Submission,
)


class AssessmentTemplateSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)

    class Meta:
        model = AssessmentTemplate
        fields = (
            "id",
            "course",
            "course_title",
            "created_by",
            "title",
            "instructions",
            "kind",
            "maximum_score",
            "created_at",
        )
        read_only_fields = ("id", "created_by", "created_at")

    def validate_maximum_score(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Maximum score must be greater than zero."
            )
        return value


class AssessmentSerializer(serializers.ModelSerializer):
    course = serializers.UUIDField(source="template.course_id", read_only=True)
    course_title = serializers.CharField(source="template.course.title", read_only=True)
    template_title = serializers.CharField(source="template.title", read_only=True)
    created_by = serializers.UUIDField(source="template.created_by_id", read_only=True)
    title = serializers.CharField(source="template.title", read_only=True)
    instructions = serializers.CharField(source="template.instructions", read_only=True)
    kind = serializers.ChoiceField(
        source="template.kind",
        choices=AssessmentTemplate.Kind.choices,
        read_only=True,
    )
    maximum_score = serializers.DecimalField(
        source="template.maximum_score",
        max_digits=7,
        decimal_places=2,
        read_only=True,
    )
    class_group_name = serializers.CharField(
        source="class_group.name", read_only=True, allow_null=True
    )
    submission_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Assessment
        fields = (
            "id",
            "template",
            "template_title",
            "title",
            "instructions",
            "course",
            "course_title",
            "class_group",
            "class_group_name",
            "created_by",
            "kind",
            "maximum_score",
            "due_at",
            "late_until",
            "max_attempts",
            "weight",
            "status",
            "submission_count",
            "created_at",
        )
        read_only_fields = (
            "id",
            "template_title",
            "title",
            "instructions",
            "course",
            "course_title",
            "created_by",
            "kind",
            "maximum_score",
            "status",
            "submission_count",
            "created_at",
        )

    def validate(self, attrs):
        template = attrs.get("template", getattr(self.instance, "template", None))
        group = attrs.get("class_group", getattr(self.instance, "class_group", None))
        if self.instance and "class_group" not in attrs:
            group = self.instance.class_group
        if not self.instance and not group:
            raise serializers.ValidationError(
                {"class_group": "Select the class for this assessment."}
            )
        if group and template and group.course_id != template.course_id:
            raise serializers.ValidationError(
                {"class_group": "The class group must belong to the template's course."}
            )
        if group and not group.is_active:
            raise serializers.ValidationError(
                {"class_group": "Select an active class group."}
            )
        due_at = attrs.get("due_at", getattr(self.instance, "due_at", None))
        late_until = attrs.get("late_until", getattr(self.instance, "late_until", None))
        if late_until and (not due_at or late_until <= due_at):
            raise serializers.ValidationError(
                {"late_until": "The late cutoff must be after the due date."}
            )
        if (
            self.instance
            and self.instance.submissions.exists()
            and template
            and template.id != self.instance.template_id
        ):
            raise serializers.ValidationError(
                {"template": "Template cannot change after submissions are received."}
            )
        return attrs

    def validate_max_attempts(self, value):
        if value < 1:
            raise serializers.ValidationError("At least one attempt is required.")
        return value


class SubmissionSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    registration_number = serializers.CharField(
        source="student.registration_number", read_only=True
    )
    file_name = serializers.CharField(source="file.original_name", read_only=True)
    assessment_title = serializers.CharField(source="assessment.title", read_only=True)

    class Meta:
        model = Submission
        fields = (
            "id",
            "assessment",
            "assessment_title",
            "student",
            "student_name",
            "registration_number",
            "attempt_number",
            "file",
            "file_name",
            "note",
            "is_late",
            "submitted_at",
        )
        read_only_fields = (
            "id",
            "student",
            "attempt_number",
            "is_late",
            "submitted_at",
            "student_name",
            "registration_number",
            "file_name",
            "assessment_title",
        )

    def get_student_name(self, obj) -> str:
        return f"{obj.student.first_name} {obj.student.last_name}"

    def validate(self, attrs):
        request = self.context["request"]
        file = attrs.get("file")
        if file and (
            file.status != StoredFile.Status.READY
            or file.purpose != StoredFile.Purpose.SUBMISSION
            or file.owner_user_id != request.user.id
        ):
            raise serializers.ValidationError(
                {"file": "Select a ready submission file that you uploaded."}
            )
        return attrs


class GradeSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    registration_number = serializers.CharField(
        source="enrollment.student.registration_number", read_only=True
    )
    assessment_title = serializers.CharField(source="assessment.title", read_only=True)
    maximum_score = serializers.DecimalField(
        source="assessment.maximum_score",
        max_digits=7,
        decimal_places=2,
        read_only=True,
    )
    attempt_number = serializers.SerializerMethodField()
    official_score = serializers.DecimalField(
        source="official_revision.score",
        max_digits=7,
        decimal_places=2,
        allow_null=True,
        read_only=True,
    )
    official_published_at = serializers.DateTimeField(
        source="official_revision.published_at", allow_null=True, read_only=True
    )
    regrade_pending = serializers.SerializerMethodField()
    is_late = serializers.BooleanField(read_only=True)
    change_note = serializers.CharField(
        write_only=True, required=False, allow_blank=False
    )

    class Meta:
        model = Grade
        fields = (
            "id",
            "assessment",
            "enrollment",
            "submission",
            "source",
            "attempt_number",
            "student_name",
            "registration_number",
            "assessment_title",
            "maximum_score",
            "score",
            "official_score",
            "official_published_at",
            "regrade_pending",
            "feedback",
            "status",
            "revision",
            "is_late",
            "graded_by",
            "approved_by",
            "approved_at",
            "published_by",
            "published_at",
            "review_note",
            "change_note",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "source",
            "attempt_number",
            "status",
            "revision",
            "graded_by",
            "approved_by",
            "approved_at",
            "published_by",
            "published_at",
            "review_note",
            "is_late",
            "updated_at",
            "student_name",
            "registration_number",
            "assessment_title",
            "maximum_score",
            "official_score",
            "official_published_at",
            "regrade_pending",
        )

    def get_student_name(self, obj) -> str:
        student = obj.enrollment.student
        return f"{student.first_name} {student.last_name}"

    def get_attempt_number(self, obj) -> int | None:
        return obj.submission.attempt_number if obj.submission_id else None

    def get_regrade_pending(self, obj) -> bool:
        return bool(obj.official_revision_id and obj.status != Grade.Status.PUBLISHED)

    def validate(self, attrs):
        assessment = attrs.get("assessment", getattr(self.instance, "assessment", None))
        enrollment = attrs.get("enrollment", getattr(self.instance, "enrollment", None))
        submission = attrs.get("submission", getattr(self.instance, "submission", None))
        if self.instance and assessment != self.instance.assessment:
            raise serializers.ValidationError(
                {"assessment": "A grade cannot be moved to another assessment."}
            )
        if self.instance and enrollment != self.instance.enrollment:
            raise serializers.ValidationError(
                {"enrollment": "A grade cannot be moved to another enrollment."}
            )
        if (
            assessment
            and enrollment
            and (
                assessment.template.course_id != enrollment.course_id
                or (
                    assessment.class_group_id
                    and assessment.class_group_id != enrollment.class_group_id
                )
            )
        ):
            raise serializers.ValidationError(
                {"enrollment": "The enrollment must belong to this assessment's class."}
            )
        if submission and (
            not assessment
            or not enrollment
            or submission.assessment_id != assessment.id
            or submission.student_id != enrollment.student_id
        ):
            raise serializers.ValidationError(
                {
                    "submission": "The submission must belong to this assessment and enrollment."
                }
            )
        score = attrs.get("score", getattr(self.instance, "score", None))
        if self.instance is None and score is None:
            raise serializers.ValidationError(
                {"score": "A staff-recorded grade requires a score."}
            )
        if assessment and score is not None and score > assessment.maximum_score:
            raise serializers.ValidationError(
                {"score": "Score cannot exceed the assessment maximum."}
            )
        if self.instance and self.instance.status not in {
            Grade.Status.DRAFT,
            Grade.Status.REJECTED,
            Grade.Status.PUBLISHED,
        }:
            raise serializers.ValidationError(
                {"status": "Only draft or returned grades can be edited."}
            )
        return attrs

    def create(self, validated_data):
        validated_data.pop("change_note", None)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("change_note", None)
        return super().update(instance, validated_data)

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get("request")
        if (
            request
            and request.user.has_role(Role.STUDENT)
            and instance.official_revision_id
        ):
            official = instance.official_revision
            data.update(
                {
                    "score": (
                        str(official.score) if official.score is not None else None
                    ),
                    "feedback": official.feedback,
                    "status": official.status,
                    "revision": official.revision,
                    "is_late": official.is_late,
                    "graded_by": (
                        str(official.changed_by_id) if official.changed_by_id else None
                    ),
                    "approved_by": (
                        str(official.approved_by_id)
                        if official.approved_by_id
                        else None
                    ),
                    "approved_at": official.approved_at,
                    "published_by": (
                        str(official.published_by_id)
                        if official.published_by_id
                        else None
                    ),
                    "published_at": official.published_at,
                    "review_note": "",
                }
            )
        return data


class GradebookEntrySerializer(serializers.Serializer):
    grade_id = serializers.UUIDField()
    score = serializers.DecimalField(max_digits=7, decimal_places=2, allow_null=True)
    official_score = serializers.DecimalField(
        max_digits=7, decimal_places=2, allow_null=True
    )
    status = serializers.ChoiceField(choices=Grade.Status.choices)
    revision = serializers.IntegerField()
    regrade_pending = serializers.BooleanField()


class GradebookAssessmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    class_group = serializers.UUIDField(allow_null=True)
    title = serializers.CharField()
    kind = serializers.ChoiceField(choices=Assessment.Kind.choices)
    maximum_score = serializers.DecimalField(max_digits=7, decimal_places=2)
    due_at = serializers.DateTimeField(allow_null=True)
    late_until = serializers.DateTimeField(allow_null=True)
    max_attempts = serializers.IntegerField()


class GradebookStudentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    enrollment_id = serializers.UUIDField()
    class_group = serializers.UUIDField(allow_null=True)
    registration_number = serializers.CharField()
    name = serializers.CharField()
    grades = serializers.DictField(child=GradebookEntrySerializer())


class GradebookResponseSerializer(serializers.Serializer):
    course = serializers.DictField(child=serializers.CharField())
    assessments = GradebookAssessmentSerializer(many=True)
    students = GradebookStudentSerializer(many=True)


class GradeReviewSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)


class AttemptGrantCreateSerializer(serializers.Serializer):
    enrollment = serializers.PrimaryKeyRelatedField(
        queryset=Enrollment.objects.select_related("course", "class_group", "student")
    )
    reason = serializers.CharField()
    valid_until = serializers.DateTimeField(required=False)

    def validate_reason(self, value):
        value = value.strip()
        if not value:
            raise serializers.ValidationError("Provide a reason for the grant.")
        return value

    def validate_valid_until(self, value):
        now = timezone.now()
        if value <= now or value > now + timedelta(days=30):
            raise serializers.ValidationError(
                "The grant must expire within the next 30 days."
            )
        return value


class AssessmentAttemptGrantSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()

    class Meta:
        model = AssessmentAttemptGrant
        fields = (
            "id",
            "assessment",
            "enrollment",
            "student_name",
            "granted_by",
            "reason",
            "valid_until",
            "used_at",
            "used_by",
            "used_for",
            "created_at",
        )
        read_only_fields = fields

    def get_student_name(self, obj) -> str:
        student = obj.enrollment.student
        return f"{student.first_name} {student.last_name}"


class GradeRevisionSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradeRevision
        fields = (
            "id",
            "revision",
            "submission",
            "source",
            "attempt_number",
            "score",
            "feedback",
            "status",
            "changed_by",
            "change_note",
            "approved_by",
            "approved_at",
            "published_by",
            "published_at",
            "review_note",
            "is_late",
            "attempt_grant",
            "created_at",
        )
        read_only_fields = fields
