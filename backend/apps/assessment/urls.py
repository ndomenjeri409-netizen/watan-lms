from django.urls import path
from rest_framework.routers import DefaultRouter

from .transcripts import StudentTranscriptView
from .views import AssessmentViewSet, GradebookView, GradeViewSet, SubmissionViewSet

router = DefaultRouter()
router.register("assessments", AssessmentViewSet, basename="assessment")
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
        "transcripts/<uuid:student_id>/",
        StudentTranscriptView.as_view(),
        name="student-transcript",
    ),
    *router.urls,
]
