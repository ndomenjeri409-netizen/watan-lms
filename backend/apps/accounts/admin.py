from django.contrib import admin

from .models import RoleAssignment, RoleScope, User


class RoleAssignmentInline(admin.TabularInline):
    model = RoleAssignment
    fk_name = "user"
    extra = 0


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "display_name", "role", "is_active")
    list_filter = ("is_active", "assignments__role", "assignments__unit")
    search_fields = ("email", "display_name", "firebase_uid")
    inlines = (RoleAssignmentInline,)


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "unit", "is_active", "granted_by")
    list_filter = ("role", "unit", "is_active")
    search_fields = ("user__email", "user__display_name")
    list_select_related = ("user", "unit", "granted_by")


@admin.register(RoleScope)
class RoleScopeAdmin(admin.ModelAdmin):
    list_display = ("user", "department")
    list_select_related = ("user", "department")
