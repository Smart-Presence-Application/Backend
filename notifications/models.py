from django.conf import settings
from django.db import models

from academics.models import ClassSection
from common.choices import UserRole
from common.storage import (
    notification_attachment_storage,
    notification_attachment_upload_path,
)
from schools.models import School
from students.models import Student


class AttachmentKind(models.TextChoices):
    IMAGE = "IMAGE", "Image"
    VIDEO = "VIDEO", "Video"
    AUDIO = "AUDIO", "Audio"
    PDF = "PDF", "PDF"
    DOCUMENT = "DOCUMENT", "Document"
    OTHER = "OTHER", "Other"


class Notification(models.Model):
    """
    A message with optional attachments, sent to an audience.

    The audience is described by the ``to_*`` flags (whole roles),
    narrowed by ``target_schools`` / ``target_class_sections``, plus
    any individually chosen ``target_users`` and the parents of
    ``target_students``. It is resolved into NotificationRecipient rows
    when the notification is sent, so the audience is fixed at that
    moment and every recipient has their own read state. ``school`` is
    the sender's school, null for Super Admin notifications.
    """

    title = models.CharField(max_length=255)
    message = models.TextField(blank=True, default="")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="sent_notifications",
    )
    sender_role = models.CharField(max_length=20, choices=UserRole.choices)
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="notifications",
    )

    to_school_admins = models.BooleanField(default=False)
    to_teachers = models.BooleanField(default=False)
    to_parents = models.BooleanField(default=False)

    target_schools = models.ManyToManyField(
        School,
        blank=True,
        related_name="+",
    )
    target_class_sections = models.ManyToManyField(
        ClassSection,
        blank=True,
        related_name="+",
    )
    target_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="+",
    )
    target_students = models.ManyToManyField(
        Student,
        blank=True,
        related_name="+",
    )

    recipient_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["school", "created_at"],
                name="notification_school_idx",
            ),
        ]

    def __str__(self) -> str:
        return self.title


class NotificationAttachment(models.Model):
    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(
        upload_to=notification_attachment_upload_path,
        storage=notification_attachment_storage,
        max_length=255,
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=100, blank=True, default="")
    size = models.PositiveBigIntegerField(default=0)
    kind = models.CharField(
        max_length=10,
        choices=AttachmentKind.choices,
        default=AttachmentKind.OTHER,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_attachments"
        ordering = ["id"]

    def __str__(self) -> str:
        return self.original_name


class NotificationRecipient(models.Model):
    """
    One user's copy of a notification, with their read state.
    """

    notification = models.ForeignKey(
        Notification,
        on_delete=models.CASCADE,
        related_name="recipients",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_inbox",
    )
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notification_recipients"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["notification", "user"],
                name="unique_notification_recipient",
            ),
        ]
        indexes = [
            models.Index(
                fields=["user", "is_read"],
                name="notification_inbox_unread_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.notification} -> {self.user}"


class PushSubscription(models.Model):
    """
    One browser or installed app that accepted push notifications.

    The endpoint identifies the device; if another user signs in on it,
    the row moves to them so the previous user stops receiving pushes.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="push_subscriptions",
    )
    endpoint = models.URLField(max_length=1000, unique=True)
    p256dh = models.CharField(max_length=255)
    auth = models.CharField(max_length=255)
    user_agent = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "push_subscriptions"

    def __str__(self) -> str:
        return f"Push subscription of {self.user}"
