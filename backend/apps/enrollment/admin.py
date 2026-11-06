from django.contrib import admin

from .models import Application, CourseAccess, Enrollment


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = (
        "first_name",
        "last_name",
        "email",
        "course",
        "status",
        "created_at",
    )
    list_filter = ("status", "department", "course")
    search_fields = ("first_name", "last_name", "email", "phone")
    readonly_fields = ("student", "reviewed_by", "reviewed_at")


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "status", "created_at")
    list_filter = ("status", "course")
    search_fields = ("student__registration_number", "course__title", "course__code")
    readonly_fields = ("approved_by", "activated_at")


@admin.register(CourseAccess)
class CourseAccessAdmin(admin.ModelAdmin):
    list_display = ("student", "course", "is_active", "created_at")
    list_filter = ("is_active", "course")
    search_fields = ("student__registration_number", "course__title", "course__code")
