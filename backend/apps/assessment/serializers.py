from django.utils import timezone
from rest_framework import serializers

from apps.files.models import StoredFile

from .models import Assessment, Grade, Submission


class AssessmentSerializer(serializers.ModelSerializer):
    course_title = serializers.CharField(source="course.title", read_only=True)
    class_group_name = serializers.CharField(
        source="class_group.name", read_only=True, allow_null=True
    )
    submission_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Assessment
        fields = (
            "id",
            "course",
            "course_title",
            "class_group",
            "class_group_name",
            "created_by",
            "title",
            "instructions",
            "kind",
            "maximum_score",
            "due_at",
            "status",
            "submission_count",
            "created_at",
        )
        read_only_fields = (
            "id",
            "created_by",
            "status",
            "submission_count",
            "created_at",
        )

    def validate(self, attrs):
        course = attrs.get("course", getattr(self.instance, "course", None))
        group = attrs.get("class_group", getattr(self.instance, "class_group", None))
        if self.instance and "class_group" not in attrs:
            group = self.instance.class_group
        if group and course and group.course_id != course.id:
            raise serializers.ValidationError(
                {"class_group": "The class group must belong to this course."}
            )
        if group and not group.is_active:
            raise serializers.ValidationError(
                {"class_group": "Select an active class group."}
            )
        if (
            self.instance
            and self.instance.submissions.exists()
            and course
            and course.id != self.instance.course_id
        ):
            raise serializers.ValidationError(
                {"course": "Course cannot change after submissions are received."}
            )
        return attrs


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
            "submitted_at",
        )
        read_only_fields = (
            "id",
            "student",
            "attempt_number",
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
        assessment = attrs.get("assessment")
        file = attrs.get("file")
        if assessment and (
            assessment.status != Assessment.Status.PUBLISHED
            or (assessment.due_at and assessment.due_at < timezone.now())
        ):
            raise serializers.ValidationError(
                {"assessment": "This assessment is not accepting submissions."}
            )
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
        source="submission.student.registration_number", read_only=True
    )
    assessment_title = serializers.CharField(
        source="submission.assessment.title", read_only=True
    )
    maximum_score = serializers.DecimalField(
        source="submission.assessment.maximum_score",
        max_digits=7,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = Grade
        fields = (
            "id",
            "submission",
            "student_name",
            "registration_number",
            "assessment_title",
            "maximum_score",
            "score",
            "feedback",
            "status",
            "revision",
            "graded_by",
            "approved_by",
            "approved_at",
            "published_at",
            "review_note",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "status",
            "revision",
            "graded_by",
            "approved_by",
            "approved_at",
            "published_at",
            "review_note",
            "updated_at",
            "student_name",
            "registration_number",
            "assessment_title",
            "maximum_score",
        )

    def get_student_name(self, obj) -> str:
        return f"{obj.submission.student.first_name} {obj.submission.student.last_name}"

    def validate(self, attrs):
        submission = attrs.get("submission", getattr(self.instance, "submission", None))
        if self.instance and submission != self.instance.submission:
            raise serializers.ValidationError(
                {"submission": "A grade cannot be moved to another submission."}
            )
        score = attrs.get("score", getattr(self.instance, "score", None))
        if (
            submission
            and score is not None
            and score > submission.assessment.maximum_score
        ):
            raise serializers.ValidationError(
                {"score": "Score cannot exceed the assessment maximum."}
            )
        if self.instance and self.instance.status not in {
            Grade.Status.DRAFT,
            Grade.Status.REJECTED,
        }:
            raise serializers.ValidationError(
                {"status": "Only draft or returned grades can be edited."}
            )
        return attrs


class GradebookEntrySerializer(serializers.Serializer):
    grade_id = serializers.UUIDField()
    score = serializers.DecimalField(max_digits=7, decimal_places=2)
    status = serializers.ChoiceField(choices=Grade.Status.choices)
    revision = serializers.IntegerField()


class GradebookAssessmentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    title = serializers.CharField()
    kind = serializers.ChoiceField(choices=Assessment.Kind.choices)
    maximum_score = serializers.DecimalField(max_digits=7, decimal_places=2)
    due_at = serializers.DateTimeField(allow_null=True)


class GradebookStudentSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    registration_number = serializers.CharField()
    name = serializers.CharField()
    grades = serializers.DictField(child=GradebookEntrySerializer())


class GradebookResponseSerializer(serializers.Serializer):
    course = serializers.DictField(child=serializers.CharField())
    assessments = GradebookAssessmentSerializer(many=True)
    students = GradebookStudentSerializer(many=True)


class GradeReviewSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True)
