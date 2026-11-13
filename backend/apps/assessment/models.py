from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.accounts.roles import GLOBAL_READ_ROLES, Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


def _teacher_scope(user, course_path, class_group_path):
    unit_ids = user.unit_ids_for(Role.TEACHER)
    if not unit_ids:
        return Q(pk__in=[])

    return Q(
        **{
            f"{course_path}__unit_id__in": unit_ids,
            f"{course_path}__teacher_assignments__teacher": user,
            f"{course_path}__teacher_assignments__can_edit_content": True,
            f"{course_path}__teacher_assignments__is_active": True,
        }
    ) | Q(
        **{
            f"{course_path}__unit_id__in": unit_ids,
            f"{class_group_path}__teacher_assignments__teacher": user,
            f"{class_group_path}__teacher_assignments__is_active": True,
        }
    )


class AssessmentTemplateQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(course__department_id__in=department_ids)

        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(course__unit_id__in=manager_unit_ids)

        teacher_unit_ids = user.unit_ids_for(Role.TEACHER)
        if teacher_unit_ids:
            scope |= Q(
                course__unit_id__in=teacher_unit_ids,
                course__teacher_assignments__teacher=user,
                course__teacher_assignments__can_edit_content=True,
                course__teacher_assignments__is_active=True,
            )

        return self.filter(scope).distinct()


class AssessmentQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(template__course__department_id__in=department_ids)

        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(template__course__unit_id__in=manager_unit_ids)

        scope |= _teacher_scope(user, "template__course", "class_group")

        if user.has_role(Role.STUDENT):
            from apps.enrollment.models import CourseAccess, Enrollment

            scope |= Q(
                status=Assessment.Status.PUBLISHED,
                class_group__enrollments__student__user=user,
                class_group__enrollments__status__in=(
                    Enrollment.Status.ACTIVE,
                    Enrollment.Status.COMPLETED,
                ),
                class_group__is_active=True,
            ) | Q(
                status=Assessment.Status.PUBLISHED,
                class_group__isnull=True,
                template__course_id__in=CourseAccess.objects.for_user(user)
                .filter(is_active=True)
                .values("course_id"),
            )

        return self.filter(scope).distinct()


class SubmissionQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(assessment__template__course__department_id__in=department_ids)

        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(assessment__template__course__unit_id__in=manager_unit_ids)

        scope |= _teacher_scope(
            user, "assessment__template__course", "assessment__class_group"
        )
        if user.has_role(Role.STUDENT):
            scope |= Q(student__user=user)

        return self.filter(scope).distinct()


class GradeQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(assessment__template__course__department_id__in=department_ids)

        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(assessment__template__course__unit_id__in=manager_unit_ids)

        scope |= _teacher_scope(
            user,
            "assessment__template__course",
            "assessment__class_group",
        )
        if user.has_role(Role.STUDENT):
            scope |= Q(
                enrollment__student__user=user,
                official_revision__status="PUBLISHED",
            )

        return self.filter(scope).distinct()


class AssessmentAttemptGrantQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated:
            return self.none()
        if user.has_role_global(*GLOBAL_READ_ROLES):
            return self

        scope = Q(pk__in=[])
        department_ids = user.department_ids_for_hod()
        if department_ids:
            scope |= Q(assessment__template__course__department_id__in=department_ids)
        manager_unit_ids = user.unit_ids_for(Role.UNIT_MANAGER)
        if manager_unit_ids:
            scope |= Q(assessment__template__course__unit_id__in=manager_unit_ids)
        scope |= _teacher_scope(
            user, "assessment__template__course", "assessment__class_group"
        )
        if user.has_role(Role.STUDENT):
            scope |= Q(enrollment__student__user=user)
        return self.filter(scope).distinct()


class AssessmentTemplate(BaseModel):
    class Kind(models.TextChoices):
        ASSIGNMENT = "ASSIGNMENT", "Assignment"
        QUIZ = "QUIZ", "Quiz"
        EXAM = "EXAM", "Exam"
        PROJECT = "PROJECT", "Project"

    course = models.ForeignKey(
        "academics.Course",
        on_delete=models.PROTECT,
        related_name="assessment_templates",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_assessments",
    )
    title = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    maximum_score = models.DecimalField(max_digits=7, decimal_places=2)
    objects = AssessmentTemplateQuerySet.as_manager()

    class Meta:
        ordering = ("course__title", "title")
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(maximum_score__gt=0),
                name="assessment_template_maximum_score_positive",
            )
        ]

    def __str__(self):
        return self.title


class Assessment(BaseModel):
    Kind = AssessmentTemplate.Kind

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"

    template = models.ForeignKey(
        AssessmentTemplate, on_delete=models.PROTECT, related_name="instances"
    )
    class_group = models.ForeignKey(
        "scheduling.ClassGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assessments",
    )
    due_at = models.DateTimeField(null=True, blank=True)
    late_until = models.DateTimeField(null=True, blank=True)
    max_attempts = models.PositiveSmallIntegerField(default=1)
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )

    objects = AssessmentQuerySet.as_manager()

    class Meta:
        ordering = ("due_at", "template__title")
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(weight__gt=0), name="assessment_instance_weight_positive"
            ),
            models.CheckConstraint(
                condition=Q(max_attempts__gte=1),
                name="assessment_max_attempts_positive",
            ),
            models.CheckConstraint(
                condition=Q(late_until__isnull=True)
                | (Q(due_at__isnull=False) & Q(late_until__gt=models.F("due_at"))),
                name="assessment_late_after_due",
            ),
        ]
        indexes = [  # noqa: RUF012
            models.Index(
                fields=("class_group", "status", "due_at"),
                name="assessment_class_status_idx",
            )
        ]

    @property
    def course(self):
        return self.template.course

    @property
    def created_by(self):
        return self.template.created_by

    @property
    def title(self):
        return self.template.title

    @property
    def instructions(self):
        return self.template.instructions

    @property
    def kind(self):
        return self.template.kind

    @property
    def maximum_score(self):
        return self.template.maximum_score

    def __str__(self):
        return f"{self.template.title} — {self.class_group or 'Legacy course instance'}"


class Submission(BaseModel):
    assessment = models.ForeignKey(
        Assessment, on_delete=models.PROTECT, related_name="submissions"
    )
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="submissions"
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    file = models.ForeignKey(
        "files.StoredFile", on_delete=models.PROTECT, related_name="submissions"
    )
    note = models.TextField(blank=True)
    is_late = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(auto_now_add=True)

    objects = SubmissionQuerySet.as_manager()

    class Meta:
        ordering = ("-attempt_number",)
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("assessment", "student", "attempt_number"),
                name="unique_assessment_student_attempt",
            )
        ]


class Grade(BaseModel):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        PUBLISHED = "PUBLISHED", "Published"
        REJECTED = "REJECTED", "Rejected"

    class Source(models.TextChoices):
        SUBMISSION = "SUBMISSION", "Submission"
        STAFF_RECORDED = "STAFF_RECORDED", "Staff recorded"

    assessment = models.ForeignKey(
        Assessment, on_delete=models.PROTECT, related_name="grades"
    )
    enrollment = models.ForeignKey(
        "enrollment.Enrollment", on_delete=models.PROTECT, related_name="grades"
    )
    submission = models.ForeignKey(
        Submission,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="current_grades",
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    revision = models.PositiveSmallIntegerField(default=1)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="grades_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="grades_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="grades_published",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    official_revision = models.ForeignKey(
        "GradeRevision",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="official_for",
    )

    objects = GradeQuerySet.as_manager()

    class Meta:
        ordering = ("enrollment__student__registration_number",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(score__isnull=True) | Q(score__gte=0),
                name="grade_score_nonnegative",
            ),
            models.UniqueConstraint(
                fields=("assessment", "enrollment"),
                name="unique_assessment_enrollment_grade",
            ),
        ]

    @property
    def is_late(self):
        return bool(self.submission_id and self.submission.is_late)


class GradeRevision(BaseModel):
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveSmallIntegerField()
    submission = models.ForeignKey(
        Submission,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="grade_revisions",
    )
    source = models.CharField(max_length=16, choices=Grade.Source.choices)
    attempt_number = models.PositiveSmallIntegerField(null=True, blank=True)
    score = models.DecimalField(max_digits=7, decimal_places=2, null=True, blank=True)
    feedback = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Grade.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="grade_revisions",
    )
    change_note = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="approved_grade_revisions",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="published_grade_revisions",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    is_late = models.BooleanField(default=False)
    attempt_grant = models.ForeignKey(
        "AssessmentAttemptGrant",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="grade_revisions",
    )
    legacy_grade_id = models.UUIDField(null=True, blank=True)
    legacy_revision = models.PositiveSmallIntegerField(null=True, blank=True)
    migration_generated = models.BooleanField(default=False)

    class Meta:
        ordering = ("grade_id", "revision")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("grade", "revision"), name="unique_grade_revision"
            )
        ]


class AssessmentAttemptGrant(BaseModel):
    assessment = models.ForeignKey(
        Assessment, on_delete=models.PROTECT, related_name="attempt_grants"
    )
    enrollment = models.ForeignKey(
        "enrollment.Enrollment",
        on_delete=models.PROTECT,
        related_name="attempt_grants",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="assessment_attempt_grants",
    )
    reason = models.TextField()
    valid_until = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    used_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="used_assessment_attempt_grants",
    )
    used_for = models.CharField(
        max_length=16, choices=Grade.Source.choices, null=True, blank=True
    )

    objects = AssessmentAttemptGrantQuerySet.as_manager()


class GradeSupersession(BaseModel):
    grade = models.ForeignKey(
        Grade, on_delete=models.PROTECT, related_name="supersessions"
    )
    previous_revision = models.ForeignKey(
        GradeRevision,
        on_delete=models.PROTECT,
        related_name="superseded_by_records",
    )
    replacement_revision = models.ForeignKey(
        GradeRevision,
        on_delete=models.PROTECT,
        related_name="supersedes_records",
    )
    superseded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grade_supersessions",
    )

    class Meta:
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("previous_revision",), name="unique_grade_supersession"
            )
        ]


class TranscriptVersion(BaseModel):
    student = models.ForeignKey(
        "people.Student", on_delete=models.PROTECT, related_name="transcript_versions"
    )
    version = models.PositiveSmallIntegerField()
    snapshot = models.JSONField()
    is_revised = models.BooleanField(default=False)
    revision_date = models.DateTimeField(null=True, blank=True)
    trigger_revision = models.ForeignKey(
        GradeRevision,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transcript_versions",
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="transcripts_generated",
    )

    class Meta:
        ordering = ("student_id", "version")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("student", "version"), name="unique_student_transcript_version"
            )
        ]


class LegacyGradeArchive(BaseModel):
    grade = models.ForeignKey(
        Grade, on_delete=models.PROTECT, related_name="legacy_attempts"
    )
    legacy_grade_id = models.UUIDField(unique=True)
    submission = models.ForeignKey(
        Submission, on_delete=models.PROTECT, related_name="legacy_grade_archives"
    )
    score = models.DecimalField(max_digits=7, decimal_places=2)
    feedback = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Grade.Status.choices)
    revision = models.PositiveSmallIntegerField()
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="legacy_grades_created",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="legacy_grades_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)
    legacy_created_at = models.DateTimeField()
    legacy_updated_at = models.DateTimeField()
