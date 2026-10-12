from django.contrib import admin

from .models import TeacherAttendance, TeacherAttendanceSettings


@admin.register(TeacherAttendanceSettings)
class TeacherAttendanceSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "school",
        "full_day_minutes",
        "half_day_minutes",
        "updated_at",
    )
    list_select_related = ("school",)


@admin.register(TeacherAttendance)
class TeacherAttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "teacher",
        "school",
        "status",
        "check_in_captured_at",
        "check_out_captured_at",
        "worked_minutes",
        "day_type",
    )
    list_filter = (
        "status",
        "day_type",
        "school",
    )
    search_fields = (
        "teacher__employee_id",
        "teacher__user__name",
    )
    date_hierarchy = "date"
    list_select_related = (
        "teacher",
        "teacher__user",
        "school",
    )
    readonly_fields = (
        "check_in_captured_at",
        "check_out_captured_at",
        "check_in_image_hash",
        "check_out_image_hash",
        "created_at",
        "updated_at",
    )
