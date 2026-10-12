"""Notification API views."""

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import F
from django.utils import timezone
from rest_framework import filters, generics
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from common.pagination import StandardResultsPagination
from common.permissions import IsNotificationSender
from common.responses import (
    created_response,
    deleted_response,
    success_response,
    updated_response,
)

from . import services
from .selectors import can_delete, get_inbox, get_read_summary, get_sent_by
from .models import PushSubscription
from .push import push_enabled
from .serializers import (
    InboxSerializer,
    MarkReadSerializer,
    NotificationCreateSerializer,
    PushSubscribeSerializer,
    PushUnsubscribeSerializer,
    RecipientStatusSerializer,
    SentNotificationSerializer,
)


def to_drf_error(exc: DjangoValidationError) -> ValidationError:
    if hasattr(exc, "error_dict"):
        return ValidationError(exc.message_dict)

    return ValidationError({"detail": exc.messages})


class PaginatedListMixin:
    pagination_class = StandardResultsPagination
    list_message = "Fetched successfully."

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)

        return success_response(
            self.list_message,
            self.get_serializer(queryset, many=True).data,
        )


class SentNotificationListCreateAPIView(PaginatedListMixin, generics.ListCreateAPIView):
    """
    Send a notification, or list the ones you sent.
    """

    permission_classes = [IsAuthenticated, IsNotificationSender]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    filter_backends = [filters.SearchFilter]
    search_fields = ["title", "message"]
    list_message = "Sent notifications fetched successfully."

    def get_queryset(self):
        return get_sent_by(self.request.user)

    def get_serializer_class(self):
        if self.request.method == "POST":
            return NotificationCreateSerializer

        return SentNotificationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            notification = services.send_notification(
                actor=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        notification = get_sent_by(request.user).get(pk=notification.pk)

        return created_response(
            f"Notification sent to {notification.recipient_count} recipient(s).",
            SentNotificationSerializer(notification, context={"request": request}).data,
        )


class SentNotificationDetailAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsNotificationSender]

    def get_notification(self, pk):
        notification = get_sent_by(self.request.user).filter(pk=pk).first()

        if notification is None:
            raise NotFound("Notification not found.")

        return notification

    def get(self, request, pk, *args, **kwargs):
        notification = self.get_notification(pk)
        data = SentNotificationSerializer(
            notification,
            context={"request": request},
        ).data
        data["read_summary"] = get_read_summary(notification)

        return success_response("Notification fetched successfully.", data)

    def delete(self, request, pk, *args, **kwargs):
        notification = self.get_notification(pk)

        if not can_delete(request.user, notification):
            raise PermissionDenied("You cannot delete this notification.")

        services.delete_notification(notification=notification)

        return deleted_response("Notification deleted for all recipients.")


class SentNotificationRecipientsAPIView(PaginatedListMixin, generics.ListAPIView):
    """
    Who received a notification, who has seen it and when.

    Those who saw it come first, most recent first, then everyone who
    has not, by name. Filters: ``?is_read=true|false``, ``?role=PARENT``
    and ``?search=<name or phone>``.
    """

    permission_classes = [IsAuthenticated, IsNotificationSender]
    serializer_class = RecipientStatusSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ["user__name", "user__phone_number", "user__email"]
    list_message = "Recipients fetched successfully."

    def get_queryset(self):
        notification = get_sent_by(self.request.user).filter(pk=self.kwargs["pk"]).first()

        if notification is None:
            raise NotFound("Notification not found.")

        queryset = notification.recipients.select_related("user").order_by(
            F("read_at").desc(nulls_last=True),
            "user__name",
        )
        is_read = self.request.query_params.get("is_read")
        role = self.request.query_params.get("role")

        if is_read in ("true", "false"):
            queryset = queryset.filter(is_read=is_read == "true")

        if role:
            queryset = queryset.filter(user__role=role.upper())

        return queryset


class InboxListAPIView(PaginatedListMixin, generics.ListAPIView):
    """
    Notifications sent to you (any signed-in user, parents included),
    newest first. ``?is_read=false`` for unread only.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = InboxSerializer
    list_message = "Notifications fetched successfully."

    def get_queryset(self):
        queryset = get_inbox(self.request.user)
        is_read = self.request.query_params.get("is_read")

        if is_read in ("true", "false"):
            queryset = queryset.filter(is_read=is_read == "true")

        return queryset


class InboxDetailAPIView(generics.GenericAPIView):
    """
    Open one notification; opening it marks it read.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk, *args, **kwargs):
        item = get_inbox(request.user).filter(notification_id=pk).first()

        if item is None:
            raise NotFound("Notification not found.")

        if not item.is_read:
            item.is_read = True
            item.read_at = timezone.now()
            item.save(update_fields=["is_read", "read_at"])

        return success_response(
            "Notification fetched successfully.",
            InboxSerializer(item, context={"request": request}).data,
        )


class InboxUnreadCountAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return success_response(
            "Unread count fetched successfully.",
            {"unread": get_inbox(request.user).filter(is_read=False).count()},
        )


class InboxMarkReadAPIView(generics.GenericAPIView):
    """
    Mark the given notification ``ids`` read, or all of them.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = MarkReadSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        updated = services.mark_read(
            user=request.user,
            ids=serializer.validated_data.get("ids"),
        )

        return updated_response(
            f"{updated} notification(s) marked as read.",
            {"updated": updated},
        )


class PushPublicKeyAPIView(generics.GenericAPIView):
    """
    The VAPID public key the browser needs to subscribe, or null when
    push is not configured on this server.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return success_response(
            "Push settings fetched successfully.",
            {"public_key": settings.VAPID_PUBLIC_KEY if push_enabled() else None},
        )


class PushSubscribeAPIView(generics.GenericAPIView):
    """
    Register this device for push. Re-subscribing an endpoint moves it
    to the signed-in user.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = PushSubscribeSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        PushSubscription.objects.update_or_create(
            endpoint=data["endpoint"],
            defaults={
                "user": request.user,
                "p256dh": data["keys"]["p256dh"],
                "auth": data["keys"]["auth"],
                "user_agent": request.headers.get("User-Agent", "")[:255],
            },
        )

        return created_response("Push notifications turned on for this device.", None)


class PushUnsubscribeAPIView(generics.GenericAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PushUnsubscribeSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        PushSubscription.objects.filter(
            user=request.user,
            endpoint=serializer.validated_data["endpoint"],
        ).delete()

        return deleted_response("Push notifications turned off for this device.")
