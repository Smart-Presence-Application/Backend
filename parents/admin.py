from django.contrib import admin

from .models import Parent, ParentNotification


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "password_changed",
        "created_at",
    )
    search_fields = (
        "user__name",
        "user__phone_number",
        "students__student_id",
    )
    filter_horizontal = ("students",)
    list_select_related = ("user",)
    readonly_fields = (
        "initial_password",
        "created_at",
        "updated_at",
    )

    @admin.display(boolean=True, description="Password changed")
    def password_changed(self, obj) -> bool:
        return obj.password_changed


@admin.register(ParentNotification)
class ParentNotificationAdmin(admin.ModelAdmin):
    list_display = (
        "parent",
        "student",
        "date",
        "status",
        "is_read",
        "created_at",
    )
    list_filter = ("status", "is_read")
    list_select_related = ("parent__user", "student")
    raw_id_fields = ("parent", "student", "record")
