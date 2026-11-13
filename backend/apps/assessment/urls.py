from django.urls import path
from rest_framework.routers import DefaultRouter

from .transcripts import StudentTranscriptView, TranscriptVersionListView
from .views import (
    AssessmentAttemptGrantViewSet,
    AssessmentTemplateViewSet,
    AssessmentViewSet,
    GradebookView,
    GradeViewSet,
    SubmissionViewSet,
)

router = DefaultRouter()
router.register(
    "assessment-templates", AssessmentTemplateViewSet, basename="assessment-template"
)
router.register("assessments", AssessmentViewSet, basename="assessment")
router.register(
    "assessment-attempt-grants",
    AssessmentAttemptGrantViewSet,
    basename="assessment-attempt-grant",
)
router.register("submissions", SubmissionViewSet, basename="submission")
router.register("grades", GradeViewSet, basename="grade")

urlpatterns = [
    path("gradebook/", GradebookView.as_view(), name="gradebook"),
    path(
        "transcripts/me/",
        StudentTranscriptView.as_view(),
        name="my-transcript",
    ),
    path(
        "transcripts/me/versions/",
        TranscriptVersionListView.as_view(),
        name="my-transcript-versions",
    ),
    path(
        "transcripts/<uuid:student_id>/",
        StudentTranscriptView.as_view(),
        name="student-transcript",
    ),
    path(
        "transcripts/<uuid:student_id>/versions/",
        TranscriptVersionListView.as_view(),
        name="student-transcript-versions",
    ),
    *router.urls,
]
