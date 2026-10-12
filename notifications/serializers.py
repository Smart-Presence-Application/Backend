"""Serializers for notification APIs."""

from rest_framework import serializers

from academics.models import ClassSection
from accounts.models import User
from schools.models import School
from students.models import Student

from .models import Notification, NotificationAttachment, NotificationRecipient


class NotificationCreateSerializer(serializers.Serializer):
    """
    Compose a notification (multipart, so files can be attached).

    Audience, combined as a union:

    * ``to_school_admins`` / ``to_teachers`` / ``to_parents`` - whole
      groups, narrowed by ``schools`` (Super Admin; empty = all
      schools) and ``class_sections`` (Super / School Admin);
    * ``users`` - individual users by ID;
    * ``students`` - the parents of these students.

    What each role may target is enforced in services.
    """

    title = serializers.CharField(max_length=255)
    message = serializers.CharField(required=False, allow_blank=True, default="")

    to_school_admins = serializers.BooleanField(default=False)
    to_teachers = serializers.BooleanField(default=False)
    to_parents = serializers.BooleanField(default=False)

    schools = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        many=True,
        required=False,
    )
    class_sections = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.select_related("academic_year"),
        many=True,
        required=False,
    )
    users = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(),
        many=True,
        required=False,
    )
    students = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(),
        many=True,
        required=False,
    )
    attachments = serializers.ListField(
        child=serializers.FileField(max_length=255),
        required=False,
    )

    def validate_title(self, value):
        value = value.strip()

        if not value:
            raise serializers.ValidationError("This field may not be blank.")

        return value


class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationAttachment
        fields = [
            "id",
            "file",
            "original_name",
            "content_type",
            "size",
            "kind",
        ]
        read_only_fields = fields


class InboxSerializer(serializers.ModelSerializer):
    """
    A notification as its recipient sees it. ``id`` is the
    notification's ID.
    """

    id = serializers.IntegerField(source="notification.id", read_only=True)
    title = serializers.CharField(source="notification.title", read_only=True)
    message = serializers.CharField(source="notification.message", read_only=True)
    attachments = AttachmentSerializer(
        source="notification.attachments",
        many=True,
        read_only=True,
    )
    sender_name = serializers.CharField(
        source="notification.created_by.name",
        read_only=True,
        default=None,
    )
    sender_role = serializers.CharField(source="notification.sender_role", read_only=True)
    school_name = serializers.CharField(
        source="notification.school.name",
        read_only=True,
        default=None,
    )
    created_at = serializers.DateTimeField(source="notification.created_at", read_only=True)

    class Meta:
        model = NotificationRecipient
        fields = [
            "id",
            "title",
            "message",
            "attachments",
            "sender_name",
            "sender_role",
            "school_name",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields


class TargetUserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "name", "role"]
        read_only_fields = fields


class RecipientUserSerializer(TargetUserSerializer):
    class Meta(TargetUserSerializer.Meta):
        fields = ["id", "name", "role", "phone_number", "email"]
        read_only_fields = fields


class SentNotificationSerializer(serializers.ModelSerializer):
    """
    A notification as its sender (or a reviewing admin) sees it.
    """

    attachments = AttachmentSerializer(many=True, read_only=True)
    sender_name = serializers.CharField(source="created_by.name", read_only=True, default=None)
    school_name = serializers.CharField(source="school.name", read_only=True, default=None)
    target_users = TargetUserSerializer(many=True, read_only=True)
    read_count = serializers.IntegerField(read_only=True, default=None)
    unread_count = serializers.SerializerMethodField()
    last_read_at = serializers.DateTimeField(read_only=True, default=None)

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "attachments",
            "created_by",
            "sender_name",
            "sender_role",
            "school",
            "school_name",
            "to_school_admins",
            "to_teachers",
            "to_parents",
            "target_schools",
            "target_class_sections",
            "target_users",
            "target_students",
            "recipient_count",
            "read_count",
            "unread_count",
            "last_read_at",
            "created_at",
        ]
        read_only_fields = fields

    def get_unread_count(self, obj):
        read_count = getattr(obj, "read_count", None)
        return None if read_count is None else obj.recipient_count - read_count


class RecipientStatusSerializer(serializers.ModelSerializer):
    """
    One recipient and when they saw it (``read_at`` is null if not yet).
    """

    user = RecipientUserSerializer(read_only=True)

    class Meta:
        model = NotificationRecipient
        fields = ["user", "is_read", "read_at"]
        read_only_fields = fields


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False,
    )


class PushKeysSerializer(serializers.Serializer):
    p256dh = serializers.CharField(max_length=255)
    auth = serializers.CharField(max_length=255)


class PushSubscribeSerializer(serializers.Serializer):
    """
    The browser's PushSubscription, as returned by ``subscription.toJSON()``.
    """

    endpoint = serializers.URLField(max_length=1000)
    keys = PushKeysSerializer()


class PushUnsubscribeSerializer(serializers.Serializer):
    endpoint = serializers.URLField(max_length=1000)
