from django.contrib import admin

from .models import AIJob, AttendanceRecord, AttendanceSession, FaceRegistration


@admin.register(AIJob)
class AIJobAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "kind",
        "status",
        "processed",
        "total",
        "created_by",
        "message",
    )
    list_filter = (
        "kind",
        "status",
    )
    list_select_related = ("created_by",)
    readonly_fields = [field.name for field in AIJob._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(FaceRegistration)
class FaceRegistrationAdmin(admin.ModelAdmin):
    list_display = (
        "student",
        "source",
        "registered_by",
        "updated_at",
    )
    list_filter = ("source",)
    search_fields = (
        "student__student_id",
        "student__name",
    )
    list_select_related = (
        "student",
        "registered_by",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
    )


class AttendanceRecordInline(admin.TabularInline):
    model = AttendanceRecord
    extra = 0
    fields = (
        "student",
        "status",
        "source",
        "ai_status",
        "similarity",
        "face_registered",
        "remarks",
        "updated_by",
    )
    readonly_fields = (
        "ai_status",
        "similarity",
        "face_registered",
        "updated_by",
    )
    raw_id_fields = ("student",)


@admin.register(AttendanceSession)
class AttendanceSessionAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "class_section",
        "school",
        "status",
        "image_count",
        "detected_faces",
        "locked_by",
    )
    list_filter = (
        "status",
        "school",
        "date",
    )
    search_fields = ("school__name",)
    date_hierarchy = "date"
    list_select_related = (
        "school",
        "class_section",
        "locked_by",
    )
    readonly_fields = (
        "created_at",
        "updated_at",
        "verified_at",
        "locked_at",
    )
    inlines = [AttendanceRecordInline]
