from django.contrib import admin

from .models import Guardian, StaffProfile, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "registration_number",
        "first_name",
        "last_name",
        "department",
        "admission_year",
        "is_active",
    )
    list_filter = ("department", "admission_year", "is_active")
    search_fields = ("registration_number", "first_name", "last_name", "email")
    readonly_fields = ("registration_number",)


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "department", "job_title", "is_active")
    list_filter = ("department", "is_active")
    search_fields = ("user__email", "user__display_name", "job_title")


admin.site.register(Guardian)
