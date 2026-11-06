from django.contrib import admin

from .models import BusinessUnit, Department


@admin.register(BusinessUnit)
class BusinessUnitAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "kind", "currency", "is_active")
    list_filter = ("kind", "is_active")
    search_fields = ("code", "name")
    readonly_fields = ("id", "created_at", "updated_at")


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "unit", "campus", "is_active")
    list_filter = ("unit", "campus", "is_active")
    search_fields = ("name", "code")
