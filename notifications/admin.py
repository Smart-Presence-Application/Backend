from django.contrib import admin

from .models import Notification, NotificationAttachment, NotificationRecipient


class NotificationAttachmentInline(admin.TabularInline):
    model = NotificationAttachment
    extra = 0
    readonly_fields = (
        "original_name",
        "content_type",
        "size",
        "kind",
    )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "sender_role",
        "created_by",
        "school",
        "recipient_count",
        "created_at",
    )
    list_filter = (
        "sender_role",
        "to_school_admins",
        "to_teachers",
        "to_parents",
        "school",
    )
    search_fields = ("title", "message")
    list_select_related = ("created_by", "school")
    filter_horizontal = (
        "target_schools",
        "target_class_sections",
        "target_users",
        "target_students",
    )
    readonly_fields = ("recipient_count", "created_at", "updated_at")
    inlines = [NotificationAttachmentInline]


@admin.register(NotificationRecipient)
class NotificationRecipientAdmin(admin.ModelAdmin):
    list_display = ("notification", "user", "is_read", "read_at")
    list_filter = ("is_read",)
    list_select_related = ("notification", "user")
    raw_id_fields = ("notification", "user")
