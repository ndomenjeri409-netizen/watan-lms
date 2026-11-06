from rest_framework.routers import DefaultRouter

from .views import ApplicationViewSet, CourseAccessViewSet, EnrollmentViewSet

router = DefaultRouter()
router.register("applications", ApplicationViewSet, basename="application")
router.register("enrollments", EnrollmentViewSet, basename="enrollment")
router.register("course-access", CourseAccessViewSet, basename="course-access")

urlpatterns = router.urls
