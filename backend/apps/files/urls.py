from rest_framework.routers import DefaultRouter

from .views import FileStorageViewSet

router = DefaultRouter()
router.register("files", FileStorageViewSet, basename="file")

urlpatterns = router.urls
