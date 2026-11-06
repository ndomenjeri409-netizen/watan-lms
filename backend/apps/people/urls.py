from rest_framework.routers import DefaultRouter

from .views import GuardianViewSet, StaffProfileViewSet, StudentViewSet

router = DefaultRouter()
router.register("students", StudentViewSet, basename="student")
router.register("staff-profiles", StaffProfileViewSet, basename="staff-profile")
router.register("guardians", GuardianViewSet, basename="guardian")

urlpatterns = router.urls
