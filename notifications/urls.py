from django.urls import path

from .views import (
    InboxDetailAPIView,
    InboxListAPIView,
    InboxMarkReadAPIView,
    InboxUnreadCountAPIView,
    PushPublicKeyAPIView,
    PushSubscribeAPIView,
    PushUnsubscribeAPIView,
    SentNotificationDetailAPIView,
    SentNotificationListCreateAPIView,
    SentNotificationRecipientsAPIView,
)

app_name = "notifications"

urlpatterns = [
    path(
        "",
        SentNotificationListCreateAPIView.as_view(),
        name="notification-list-create",
    ),
    path(
        "<int:pk>/",
        SentNotificationDetailAPIView.as_view(),
        name="notification-detail",
    ),
    path(
        "<int:pk>/recipients/",
        SentNotificationRecipientsAPIView.as_view(),
        name="notification-recipients",
    ),
    path(
        "inbox/",
        InboxListAPIView.as_view(),
        name="inbox",
    ),
    path(
        "inbox/unread-count/",
        InboxUnreadCountAPIView.as_view(),
        name="inbox-unread-count",
    ),
    path(
        "inbox/read/",
        InboxMarkReadAPIView.as_view(),
        name="inbox-read",
    ),
    path(
        "push/public-key/",
        PushPublicKeyAPIView.as_view(),
        name="push-public-key",
    ),
    path(
        "push/subscribe/",
        PushSubscribeAPIView.as_view(),
        name="push-subscribe",
    ),
    path(
        "push/unsubscribe/",
        PushUnsubscribeAPIView.as_view(),
        name="push-unsubscribe",
    ),
    path(
        "inbox/<int:pk>/",
        InboxDetailAPIView.as_view(),
        name="inbox-detail",
    ),
]
