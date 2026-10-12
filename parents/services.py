"""Business logic for parents and their attendance notifications."""

import logging
import secrets

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.models import User
from attendance_student.models import AttendanceRecord, AttendanceSession
from common.choices import UserRole
from students.models import Student

from notifications.push import send_push
from .models import Parent, ParentNotification

logger = logging.getLogger(__name__)


def generate_parent_password(name: str) -> str:
    """
    ``<First name>@<4 random digits>``, e.g. "Atharva Raj Sinha" ->
    "Atharva@4956".
    """

    first = (name.split() or ["Parent"])[0]
    first = first[:1].upper() + first[1:]
    return f"{first}@{secrets.randbelow(10_000):04d}"


def _set_generated_password(parent: Parent) -> str:
    """Give the parent a new system password, flagged so the signal keeps it readable for staff."""
    password = generate_parent_password(parent.user.name)

    user = parent.user
    user.set_password(password)
    user._keep_initial_password = True

    try:
        user.save(update_fields=["password", "updated_at"])
    finally:
        user._keep_initial_password = False

    parent.initial_password = password
    parent.save(update_fields=["initial_password", "updated_at"])

    return password


def find_parent_by_phone(phone_number: str) -> Parent | None:
    return (
        Parent.objects.select_related("user")
        .filter(user__role=UserRole.PARENT, user__phone_number=phone_number)
        .first()
    )


@transaction.atomic
def create_or_link_parent(
    *,
    name: str,
    phone_number: str,
    student: Student,
    actor,
) -> tuple[Parent, bool]:
    """
    Link ``student`` to the parent with this mobile number, creating the
    parent's login first if there is none.

    A second child of the same parent therefore reuses the existing
    account and password. Returns ``(parent, created)``.
    """

    parent = find_parent_by_phone(phone_number)
    created = parent is None

    if created:
        user = User(
            name=name,
            phone_number=phone_number,
            role=UserRole.PARENT,
            email=None,
        )
        user.set_unusable_password()

        try:
            with transaction.atomic():
                user.save()
        except IntegrityError as exc:
            raise ValidationError(
                {"phone_number": "A parent with this mobile number already exists."}
            ) from exc

        parent = Parent.objects.create(user=user, created_by=actor)
        _set_generated_password(parent)

        logger.info("Parent %s created by user %s", phone_number, actor.pk)

    parent.students.add(student)

    logger.info(
        "Student %s linked to parent %s",
        student.student_id,
        phone_number,
    )

    return parent, created


@transaction.atomic
def update_parent(
    *,
    parent: Parent,
    name: str | None = None,
    phone_number: str | None = None,
) -> Parent:
    user = parent.user
    fields = ["updated_at"]

    if name is not None:
        user.name = name
        fields.append("name")

    if phone_number is not None and phone_number != user.phone_number:
        if find_parent_by_phone(phone_number) is not None:
            raise ValidationError(
                {"phone_number": "A parent with this mobile number already exists."}
            )

        user.phone_number = phone_number
        fields.append("phone_number")

    user.save(update_fields=fields)

    return parent


@transaction.atomic
def reset_parent_password(*, parent: Parent, actor) -> str:
    """Issue a fresh generated password, e.g. when the parent forgot theirs."""

    password = _set_generated_password(parent)

    logger.info(
        "Password reset for parent %s by user %s",
        parent.user.phone_number,
        actor.pk,
    )

    return password


@transaction.atomic
def unlink_student(*, parent: Parent, student: Student) -> bool:
    """
    Remove a child from a parent. A parent left with no children has
    nothing to log in for, so the account is deleted.

    Returns True if the parent account was deleted.
    """

    parent.students.remove(student)

    if parent.students.exists():
        return False

    phone_number = parent.user.phone_number
    parent.user.delete()

    logger.info("Parent %s deleted: no linked students left", phone_number)

    return True


def notify_attendance(
    *,
    session: AttendanceSession,
    record_ids: list[int] | None = None,
) -> int:
    """
    Tell each parent their child's final attendance for the session.

    A parent is notified again only when the status changed since the
    last message about that record, so unlocking and re-locking without
    changes, or an admin re-saving the same status, stays quiet. Each alert
    is also pushed to the parent's own account.

    Returns the number of notifications created.
    """

    records = AttendanceRecord.objects.filter(session=session).select_related("student")

    if record_ids is not None:
        records = records.filter(pk__in=record_ids)

    records = list(records)

    if not records:
        return 0

    last_status = {}

    for notification in ParentNotification.objects.filter(
        record__in=records,
    ).order_by("created_at"):
        last_status[(notification.parent_id, notification.record_id)] = notification.status

    links = Parent.students.through.objects.filter(
        student_id__in={record.student_id for record in records},
    ).values_list("student_id", "parent_id")

    parents_by_student: dict[int, list[int]] = {}

    for student_id, parent_id in links:
        parents_by_student.setdefault(student_id, []).append(parent_id)

    notifications = []

    for record in records:
        status_label = record.get_status_display()
        date_label = session.date.strftime("%d %b %Y")

        for parent_id in parents_by_student.get(record.student_id, []):
            key = (parent_id, record.pk)
            previous = last_status.get(key)

            if previous == record.status:
                continue

            is_update = previous is not None
            notifications.append(
                ParentNotification(
                    parent_id=parent_id,
                    student=record.student,
                    record=record,
                    date=session.date,
                    status=record.status,
                    title=(
                        f"Attendance updated: {record.student.name} - {status_label}"
                        if is_update
                        else f"{record.student.name} - {status_label} ({date_label})"
                    ),
                    message=(
                        f"{record.student.name} has been marked {status_label} "
                        f"on {date_label}."
                        + (f" Remarks: {record.remarks}" if record.remarks else "")
                    ),
                )
            )

    ParentNotification.objects.bulk_create(notifications)

    user_ids = dict(Parent.objects.filter(pk__in={n.parent_id for n in notifications}).values_list("pk", "user_id"))
    for n in notifications:
        send_push(
            [user_ids.get(n.parent_id)],
            title=n.title,
            body=n.message,
            path="alerts",
            tag=f"attendance-{n.student_id}-{n.date}",
        )

    logger.info(
        "Sent %s attendance notification(s) for session %s",
        len(notifications),
        session.pk,
    )

    return len(notifications)


def mark_notifications_read(*, parent: Parent, ids: list[int] | None = None) -> int:
    queryset = parent.notifications.filter(is_read=False)

    if ids is not None:
        queryset = queryset.filter(pk__in=ids)

    return queryset.update(is_read=True, read_at=timezone.now())
