from django.contrib import admin
from django.urls import include, path

from common.health import healthz, readyz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("readyz", readyz),
    path("api/v1/", include("apps.accounts.urls")),
    path("api/v1/", include("apps.org.urls")),
    path("api/v1/", include("apps.academics.urls")),
    path("api/v1/", include("apps.files.urls")),
    path("api/v1/", include("apps.cms.urls")),
    path("api/v1/", include("apps.people.urls")),
    path("api/v1/", include("apps.enrollment.urls")),
    path("api/v1/", include("apps.scheduling.urls")),
    path("api/v1/", include("apps.attendance.urls")),
    path("api/v1/", include("apps.assessment.urls")),
    path("api/v1/", include("apps.finance.urls")),
]
