from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.accounts.roles import Role
from common.models import BaseModel
from common.scoping import ScopedQuerySet


class AssessmentQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(course__department__role_scopes__user=user).distinct()
        if user.role == Role.TEACHER:
            return self.filter(
                Q(course__created_by=user) | Q(class_group__teacher=user)
            ).distinct()
        if user.role == Role.STUDENT:
            from apps.enrollment.models import CourseAccess

            return self.filter(
                status=Assessment.Status.PUBLISHED,
                course_id__in=CourseAccess.objects.for_user(user).values("course_id"),
            ).filter(Q(class_group__isnull=True) | Q(class_group__is_active=True))
        return self.none()


class SubmissionQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(
                assessment__course__department__role_scopes__user=user
            ).distinct()
        if user.role == Role.TEACHER:
            return self.filter(
                Q(assessment__course__created_by=user)
                | Q(assessment__class_group__teacher=user)
            ).distinct()
        if user.role == Role.STUDENT:
            return self.filter(student__user=user)
        return self.none()


class GradeQuerySet(ScopedQuerySet):
    def for_user(self, user):
        if not user.is_authenticated or not user.role:
            return self.none()
        if user.role in {Role.SUPER_ADMIN, Role.ADMIN, Role.DIRECTOR}:
            return self
        if user.role == Role.HOD:
            return self.filter(
                submission__assessment__course__department__role_scopes__user=user
            ).distinct()
        if user.role == Role.TEACHER:
            return self.filter(
                Q(submission__assessment__course__created_by=user)
                | Q(submission__assessment__class_group__teacher=user)
            ).distinct()
        if user.role == Role.STUDENT:
            return self.filter(
                submission__student__user=user,
                status=Grade.Status.PUBLISHED,
            )
        return self.none()


class Assessment(BaseModel):
    class Kind(models.TextChoices):
        ASSIGNMENT = "ASSIGNMENT", "Assignment"
        QUIZ = "QUIZ", "Quiz"
        EXAM = "EXAM", "Exam"
        PROJECT = "PROJECT", "Project"

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"
        CLOSED = "CLOSED", "Closed"

    course = models.ForeignKey(
        "academics.Course", on_delete=models.PROTECT, related_name="assessments"
    )
    class_group = models.ForeignKey(
        "scheduling.ClassGroup",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="assessments",
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
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.DRAFT
    )

    objects = AssessmentQuerySet.as_manager()

    class Meta:
        ordering = ("due_at", "title")
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(maximum_score__gt=0),
                name="assessment_maximum_score_positive",
            )
        ]
        indexes = [  # noqa: RUF012
            models.Index(
                fields=("course", "status", "due_at"),
                name="assessment_course_status_idx",
            )
        ]

    def __str__(self):
        return self.title


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
        PUBLISHED = "PUBLISHED", "Published"
        REJECTED = "REJECTED", "Rejected"

    submission = models.OneToOneField(
        Submission, on_delete=models.PROTECT, related_name="grade"
    )
    score = models.DecimalField(max_digits=7, decimal_places=2)
    feedback = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    revision = models.PositiveSmallIntegerField(default=1)
    graded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
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
    published_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    objects = GradeQuerySet.as_manager()

    class Meta:
        ordering = ("submission__student__registration_number",)
        constraints = [  # noqa: RUF012
            models.CheckConstraint(
                condition=Q(score__gte=0), name="grade_score_nonnegative"
            )
        ]


class GradeRevision(BaseModel):
    grade = models.ForeignKey(Grade, on_delete=models.PROTECT, related_name="revisions")
    revision = models.PositiveSmallIntegerField()
    score = models.DecimalField(max_digits=7, decimal_places=2)
    feedback = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=Grade.Status.choices)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="grade_revisions",
    )
    change_note = models.TextField(blank=True)

    class Meta:
        ordering = ("grade_id", "revision")
        constraints = [  # noqa: RUF012
            models.UniqueConstraint(
                fields=("grade", "revision"), name="unique_grade_revision"
            )
        ]
