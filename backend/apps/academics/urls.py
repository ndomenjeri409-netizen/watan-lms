from rest_framework.routers import DefaultRouter

from .views import (
    CourseAssignmentViewSet,
    CourseModuleViewSet,
    CourseViewSet,
    LessonViewSet,
    MaterialViewSet,
    UnitViewSet,
)

router = DefaultRouter()
router.register("courses", CourseViewSet, basename="course")
router.register(
    "course-assignments", CourseAssignmentViewSet, basename="course-assignment"
)
router.register("course-modules", CourseModuleViewSet, basename="course-module")
router.register("course-units", UnitViewSet, basename="course-unit")
router.register("lessons", LessonViewSet, basename="lesson")
router.register("materials", MaterialViewSet, basename="material")

urlpatterns = router.urls
