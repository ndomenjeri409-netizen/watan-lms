from django.contrib import admin

from .models import Course, CourseModule, Lesson, Material, Unit


class CourseModuleInline(admin.TabularInline):
    model = CourseModule
    extra = 0


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("title", "code", "department", "status", "is_active")
    list_filter = ("status", "department", "is_active")
    search_fields = ("title", "code", "slug")
    prepopulated_fields = {"slug": ("title",)}  # noqa: RUF012
    inlines = (CourseModuleInline,)


admin.site.register(Unit)
admin.site.register(Lesson)
admin.site.register(Material)
