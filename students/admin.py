from django.contrib import admin

from .models import Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = (
        "student_id",
        "name",
        "roll_number",
        "class_section",
        "school",
        "has_profile_image",
    )
    list_filter = (
        "school",
        "class_section",
    )
    search_fields = (
        "student_id",
        "name",
        "roll_number",
        "school__name",
    )
    ordering = (
        "school__name",
        "class_section",
        "roll_number",
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
        "school",
        "class_section",
    )

    @admin.display(
        boolean=True,
        description="Has image",
    )
    def has_profile_image(self, obj) -> bool:
        return obj.has_profile_image
