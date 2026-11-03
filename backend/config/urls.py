from django.contrib import admin
from django.urls import include, path

from common.health import healthz, readyz

urlpatterns = [
    path("admin/", admin.site.urls),
    path("healthz", healthz),
    path("readyz", readyz),
    path("api/v1/", include("apps.accounts.urls")),
]
