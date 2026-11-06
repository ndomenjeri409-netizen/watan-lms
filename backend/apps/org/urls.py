from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import (
    AcademicPeriodViewSet,
    BusinessUnitListView,
    CampusViewSet,
    DepartmentViewSet,
    ProgramViewSet,
)

router = DefaultRouter()
router.register("campuses", CampusViewSet, basename="campus")
router.register("departments", DepartmentViewSet, basename="department")
router.register("programs", ProgramViewSet, basename="program")
router.register("academic-periods", AcademicPeriodViewSet, basename="academic-period")

urlpatterns = [
    path("units", BusinessUnitListView.as_view(), name="unit-list"),
    *router.urls,
]
