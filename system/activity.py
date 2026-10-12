"""
Turn an API request into an activity-log entry: a readable action
("Locked attendance") and a category for filtering, then save it.

``SKIP_PATHS`` are never logged: token refreshes happen constantly and
say nothing about what anyone did. ``NOUNS`` maps the first two path
segments to a (category, noun); ``SPECIAL`` maps the last path word to a
phrase for endpoints that are actions rather than plain CRUD.
"""

import logging
import random
import re
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from common.throttling import client_ip

from .models import ActivityLog

logger = logging.getLogger(__name__)

WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")

SKIP_PATHS = ("/api/auth/refresh/",)

VERB = {"POST": "Created", "PUT": "Updated", "PATCH": "Updated", "DELETE": "Deleted"}

NOUNS = {
    ("auth", "users"): ("users", "user account"),
    ("auth", "profile"): ("account", "own profile"),
    ("schools", ""): ("schools", "school"),
    ("schools", "me"): ("schools", "school profile"),
    ("academics", "years"): ("academics", "academic year"),
    ("academics", "classes"): ("academics", "class"),
    ("academics", "sections"): ("academics", "section"),
    ("academics", "class-sections"): ("academics", "class section"),
    ("academics", "holidays"): ("academics", "holiday"),
    ("academics", "working-days"): ("academics", "working day"),
    ("teachers", ""): ("teachers", "teacher"),
    ("students", ""): ("students", "student"),
    ("parents", ""): ("parents", "parent"),
    ("parents", "me"): ("parents", "child photo"),
    ("student-attendance", "sessions"): ("attendance", "attendance"),
    ("student-attendance", "faces"): ("attendance", "face registration"),
    ("student-attendance", "verify"): ("attendance", "AI attendance"),
    ("teacher-attendance", "records"): ("teacher-attendance", "teacher attendance"),
    ("teacher-attendance", "settings"): ("teacher-attendance", "teacher attendance settings"),
    ("notifications", ""): ("notifications", "notice"),
    ("notifications", "inbox"): ("notifications", "inbox"),
    ("notifications", "push"): ("notifications", "push notifications"),
    ("system", "maintenance"): ("system", "maintenance mode"),
}

SPECIAL = {
    "lock": "Locked {noun}",
    "unlock": "Unlocked {noun}",
    "verify": "Verified {noun}",
    "status": "Changed {noun} status",
    "bulk-status": "Changed status of several user accounts",
    "bulk-upload": "Bulk uploaded {noun}s",
    "image": "Changed {noun} photo",
    "logo": "Changed school logo",
    "photo": "Uploaded child photo",
    "change-password": "Changed {noun} password",
    "reset-password": "Reset {noun} password",
    "activate": "Activated {noun}",
    "transfer": "Transferred {noun}",
    "class-section": "Changed {noun} class section",
    "records": "Edited {noun} records",
    "register": "Registered faces",
    "register-from-profile": "Registered faces from profile photos",
    "mark-weekends": "Marked weekends",
    "promote": "Promoted students",
    "read": "Marked {noun} as read",
    "subscribe": "Turned on {noun}",
    "unsubscribe": "Turned off {noun}",
    "check-in": "Checked in",
    "check-out": "Checked out",
}

def describe(method: str, path: str, status_code: int) -> tuple[str, str]:
    """``(action, category)`` for a request, ignoring the leading "api" segment."""

    parts = [p for p in path.strip("/").split("/")[1:] if p]
    words = [p for p in parts if not p.isdigit()]
    first = words[0] if words else ""
    second = words[1] if len(words) > 1 else ""

    if first in ("auth", "parents") and second == "login":
        who = "Parent" if first == "parents" else ""
        if status_code < 400:
            return (f"{who} signed in".strip().capitalize(), "auth")
        return ("Failed sign-in" if status_code != 429 else "Sign-in blocked (too many attempts)", "auth")

    if first == "auth" and second == "logout":
        return ("Signed out", "auth")

    if first == "reports":
        report = (second or "report").replace("-", " ")
        return (f"Downloaded {'all data' if report == 'all' else report} report", "reports")

    if first == "teacher-attendance" and second in ("check-in", "check-out"):
        return (SPECIAL[second], "teacher-attendance")

    if first == "student-attendance" and words[1:] == ["verify"]:
        return ("Ran AI attendance", "attendance")

    category, noun = NOUNS.get((first, second)) or NOUNS.get((first, "")) or (first or "other", (second or first).replace("-", " "))
    last = words[-1] if words else ""

    if last in SPECIAL and len(words) > 1:
        action = SPECIAL[last].format(noun=noun)
    else:
        action = f"{VERB.get(method, method.title())} {noun}"

    return (action[:1].upper() + action[1:], category)


def should_log(request) -> bool:
    """Log API writes, plus report downloads: reads, but who downloaded what matters."""

    path = request.path

    if not path.startswith("/api/") or path.startswith(SKIP_PATHS):
        return False

    if request.method in WRITE_METHODS:
        return True

    return request.method == "GET" and path.startswith("/api/reports/") and path.rstrip("/") != "/api/reports"


def actor_school(user):
    managed = getattr(user, "managed_school", None)

    if managed is not None:
        return managed

    teacher = getattr(user, "teacher_profile", None)

    return teacher.school if teacher is not None else None


def record(request, response, *, identifier: str, duration_ms: int) -> None:
    """
    Save one entry, and now and then prune entries past the retention
    period. Never raises: logging must not break the request.
    """

    try:
        user = getattr(request, "user", None)
        user = user if user is not None and user.is_authenticated else None
        action, category = describe(request.method, request.path, response.status_code)
        school = actor_school(user) if user else None

        ActivityLog.objects.create(
            actor=user,
            actor_name=user.name if user else "",
            actor_identifier=(user.email or user.phone_number or "") if user else identifier[:255],
            actor_role=user.role if user else "",
            school=school,
            school_name=school.name if school else "",
            action=action[:255],
            category=category[:50],
            method=request.method,
            path=request.path[:500],
            status_code=response.status_code,
            duration_ms=duration_ms,
            ip_address=client_ip(request)[:64],
            user_agent=request.META.get("HTTP_USER_AGENT", "")[:500],
        )

        if random.random() < 0.01:
            prune()
    except Exception:
        logger.exception("Could not write activity log for %s %s", request.method, request.path)


def prune() -> int:
    days = getattr(settings, "ACTIVITY_LOG_RETENTION_DAYS", 90)
    deleted, _ = ActivityLog.objects.filter(created_at__lt=timezone.now() - timedelta(days=days)).delete()

    return deleted


IDENTIFIER_RE = re.compile(r'"(?:email|phone_number)"\s*:\s*"([^"]{1,255})"')


def login_identifier(request) -> str:
    """What was typed into the sign-in form (never the password)."""

    try:
        match = IDENTIFIER_RE.search(request.body.decode("utf-8", "ignore"))
    except Exception:
        return ""

    return match.group(1) if match else ""
