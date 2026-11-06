from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import AttendanceRecordViewSet, AttendanceSessionViewSet, CheckInView

router = DefaultRouter()
router.register(
    "attendance/sessions", AttendanceSessionViewSet, basename="attendance-session"
)
router.register(
    "attendance/records", AttendanceRecordViewSet, basename="attendance-record"
)

urlpatterns = [
    path("attendance/check-in/", CheckInView.as_view(), name="attendance-check-in"),
    *router.urls,
]
