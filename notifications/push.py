"""
Web Push delivery.

Each browser that allows notifications registers a PushSubscription.
``send_push`` delivers a short message to every device of the given
users once the surrounding transaction commits, on a background thread
so the request that triggered it is not slowed down. Subscriptions the
push service reports as gone (404/410) are deleted.

Links are panel-relative (e.g. ``"inbox"``) and resolved per user, since
the same page lives under ``/school/...`` for one role and
``/teacher/...`` for another.
"""

import json
import logging
import threading
from collections.abc import Iterable

from django.conf import settings
from django.db import close_old_connections, transaction

from common.choices import UserRole

from .models import PushSubscription

logger = logging.getLogger(__name__)

PANEL_BASE = {
    UserRole.SUPER_ADMIN: "/admin",
    UserRole.SCHOOL_ADMIN: "/school",
    UserRole.TEACHER: "/teacher",
    UserRole.PARENT: "/parent",
}


def push_enabled() -> bool:
    return bool(settings.VAPID_PUBLIC_KEY and settings.VAPID_PRIVATE_KEY)


def send_push(user_ids: Iterable[int], *, title: str, body: str = "", path: str = "", tag: str | None = None) -> None:
    """
    Notify every device of ``user_ids`` after the current transaction commits.
    """

    ids = list({uid for uid in user_ids if uid})

    if not ids or not push_enabled():
        return

    payload = {"title": title, "body": body[:240], "path": path, "tag": tag}

    transaction.on_commit(
        lambda: threading.Thread(target=_deliver, args=(ids, payload), daemon=True).start()
    )


def _deliver(user_ids: list[int], payload: dict) -> None:
    """
    Push ``payload`` to every device of ``user_ids``. pywebpush is
    imported here so the app still starts without that optional package.
    """

    from pywebpush import WebPushException, webpush

    close_old_connections()

    try:
        subscriptions = PushSubscription.objects.filter(user_id__in=user_ids).select_related("user")

        for sub in subscriptions:
            base = PANEL_BASE.get(sub.user.role, "")
            message = {**payload, "url": f"{base}/{payload['path']}".rstrip("/") or "/"}

            try:
                webpush(
                    subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                    data=json.dumps(message),
                    vapid_private_key=settings.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": settings.VAPID_SUBJECT},
                    ttl=24 * 60 * 60,
                )
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)

                if status in (404, 410):
                    sub.delete()
                else:
                    logger.warning("Web push to subscription %s failed: %s", sub.pk, exc)
            except Exception:  # noqa: BLE001 - one bad device must not stop the others
                logger.exception("Web push to subscription %s failed", sub.pk)
    finally:
        close_old_connections()
