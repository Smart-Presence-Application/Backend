from django.contrib import admin

from .models import Teacher


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = (
        "employee_id",
        "user",
        "school",
        "class_section",
        "is_active",
        "joining_date",
    )
    list_filter = (
        "school",
        "class_section",
        "user__is_active",
        "city",
        "state",
    )
    search_fields = (
        "employee_id",
        "user__name",
        "user__email",
        "school__name",
    )
    ordering = (
        "school__name",
        "employee_id",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )
    autocomplete_fields = (
        "school",
        "class_section",
    )
    list_select_related = (
        "user",
        "school",
        "class_section",
    )

    @admin.display(
        boolean=True,
        description="Active",
        ordering="user__is_active",
    )
    def is_active(self, obj) -> bool:
        return obj.user.is_active
