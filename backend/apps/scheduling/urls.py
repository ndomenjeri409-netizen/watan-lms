from rest_framework.routers import DefaultRouter

from .views import ClassGroupViewSet, RoomViewSet, TimetableSlotViewSet

router = DefaultRouter()
router.register("rooms", RoomViewSet, basename="room")
router.register("class-groups", ClassGroupViewSet, basename="class-group")
router.register("timetable", TimetableSlotViewSet, basename="timetable-slot")

urlpatterns = router.urls
