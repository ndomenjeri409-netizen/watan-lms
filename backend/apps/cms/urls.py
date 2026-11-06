from rest_framework.routers import DefaultRouter

from .views import BlogPostViewSet, ContentPageViewSet, FAQViewSet

router = DefaultRouter()
router.register("pages", ContentPageViewSet, basename="content-page")
router.register("faqs", FAQViewSet, basename="faq")
router.register("blog", BlogPostViewSet, basename="blog-post")

urlpatterns = router.urls
