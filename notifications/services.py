"""Business logic for sending and reading notifications."""

import logging
import mimetypes
from pathlib import Path

from decouple import config
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.models import User
from common.choices import UserRole
from schools.models import School
from students.selectors import get_actor_class_section, get_students_visible_to

from .models import (
    AttachmentKind,
    Notification,
    NotificationAttachment,
    NotificationRecipient,
)
from .push import send_push
from .selectors import (
    ALLOWED_AUDIENCES,
    get_sender_pool,
    parent_users,
    school_admin_users,
    sender_role,
    sender_school,
    teacher_users,
)

logger = logging.getLogger(__name__)

MAX_NOTIFICATION_ATTACHMENTS = config("MAX_NOTIFICATION_ATTACHMENTS", default=10, cast=int)
MAX_NOTIFICATION_ATTACHMENT_MB = config("MAX_NOTIFICATION_ATTACHMENT_MB", default=50, cast=int)

BLOCKED_EXTENSIONS = {
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".sh", ".jar",
    ".js", ".mjs", ".vbs", ".html", ".htm", ".xhtml", ".svg", ".php", ".py",
}

DOCUMENT_EXTENSIONS = {
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods",
    ".odp", ".txt", ".csv", ".rtf",
}


def attachment_kind(name: str, content_type: str) -> str:
    extension = Path(name).suffix.lower()

    if content_type.startswith("image/"):
        return AttachmentKind.IMAGE

    if content_type.startswith("video/"):
        return AttachmentKind.VIDEO

    if content_type.startswith("audio/"):
        return AttachmentKind.AUDIO

    if extension == ".pdf" or content_type == "application/pdf":
        return AttachmentKind.PDF

    if extension in DOCUMENT_EXTENSIONS:
        return AttachmentKind.DOCUMENT

    return AttachmentKind.OTHER


def validate_attachments(files) -> None:
    """
    Enforce the count and size limits and refuse ``BLOCKED_EXTENSIONS``:
    files a browser could run, or that could script our own media domain.
    """

    if len(files) > MAX_NOTIFICATION_ATTACHMENTS:
        raise ValidationError(
            {"attachments": f"At most {MAX_NOTIFICATION_ATTACHMENTS} files are allowed."}
        )

    max_bytes = MAX_NOTIFICATION_ATTACHMENT_MB * 1024 * 1024
    errors = []

    for file_obj in files:
        if Path(file_obj.name).suffix.lower() in BLOCKED_EXTENSIONS:
            errors.append(f"{file_obj.name}: this file type is not allowed.")
        elif file_obj.size > max_bytes:
            errors.append(f"{file_obj.name}: larger than {MAX_NOTIFICATION_ATTACHMENT_MB} MB.")
        elif file_obj.size == 0:
            errors.append(f"{file_obj.name}: the file is empty.")

    if errors:
        raise ValidationError({"attachments": errors})


def _save_attachments(notification: Notification, files) -> None:
    for file_obj in files:
        content_type = (
            getattr(file_obj, "content_type", "")
            or mimetypes.guess_type(file_obj.name)[0]
            or ""
        )
        NotificationAttachment.objects.create(
            notification=notification,
            file=file_obj,
            original_name=Path(file_obj.name).name[:255],
            content_type=content_type[:100],
            size=file_obj.size,
            kind=attachment_kind(file_obj.name, content_type),
        )


def _resolve_scope(
    *,
    actor,
    role: str,
    schools: list[School],
    class_sections: list,
):
    """
    The schools and (optional) class-sections the role-wide audience is
    drawn from, checked against what the sender may address. A teacher
    always sends to their own class-section.
    """

    if role == UserRole.SUPER_ADMIN:
        scope_schools = schools or list(School.objects.all())

        if schools and class_sections:
            school_ids = {school.id for school in schools}
            outside = [
                cs.pk for cs in class_sections
                if cs.academic_year.school_id not in school_ids
            ]

            if outside:
                raise ValidationError(
                    {"class_sections": f"Class sections {outside} are not in the selected schools."}
                )

        return scope_schools, class_sections or None

    if schools:
        raise ValidationError({"schools": "Only a Super Admin can choose schools."})

    school = sender_school(actor)

    if school is None:
        raise ValidationError({"detail": "You are not linked to a school."})

    if role == UserRole.SCHOOL_ADMIN:
        outside = [
            cs.pk for cs in class_sections
            if cs.academic_year.school_id != school.id
        ]

        if outside:
            raise ValidationError(
                {"class_sections": f"Class sections {outside} are not in your school."}
            )

        return [school], class_sections or None

    if class_sections:
        raise ValidationError(
            {"class_sections": "Teachers always send to their own class section."}
        )

    class_section = get_actor_class_section(actor)

    if class_section is None:
        raise ValidationError(
            {"detail": "You are not assigned to a class section, so you cannot send notifications."}
        )

    return [school], [class_section]


def resolve_recipient_ids(
    *,
    actor,
    audience: dict[str, bool],
    schools: list[School],
    class_sections: list,
    users: list[User],
    students: list,
) -> set[int]:
    role = sender_role(actor)

    if role is None:
        raise ValidationError({"detail": "You are not allowed to send notifications."})

    allowed = ALLOWED_AUDIENCES[role]
    not_allowed = [flag for flag, on in audience.items() if on and flag not in allowed]

    if not_allowed:
        raise ValidationError(
            {flag: "You cannot send notifications to this group." for flag in not_allowed}
        )

    if not (any(audience.values()) or users or students):
        raise ValidationError(
            {"detail": "Choose who should receive this: a group, individual users or students."}
        )

    scope_schools, scope_sections = _resolve_scope(
        actor=actor,
        role=role,
        schools=schools,
        class_sections=class_sections,
    )

    recipient_ids: set[int] = set()

    if audience.get("to_school_admins"):
        recipient_ids.update(school_admin_users(scope_schools).values_list("id", flat=True))

    if audience.get("to_teachers"):
        recipient_ids.update(
            teacher_users(scope_schools, scope_sections).values_list("id", flat=True)
        )

    if audience.get("to_parents"):
        recipient_ids.update(
            parent_users(scope_schools, scope_sections).values_list("id", flat=True)
        )

    if users:
        wanted = {user.pk for user in users}
        reachable = set(get_sender_pool(actor).filter(pk__in=wanted).values_list("id", flat=True))
        unreachable = sorted(wanted - reachable)

        if unreachable:
            raise ValidationError(
                {"users": f"You cannot send notifications to users {unreachable}."}
            )

        recipient_ids.update(reachable)

    if students:
        wanted = {student.pk for student in students}
        visible = set(
            get_students_visible_to(actor).filter(pk__in=wanted).values_list("id", flat=True)
        )
        hidden = sorted(wanted - visible)

        if hidden:
            raise ValidationError({"students": f"Students {hidden} are outside your scope."})

        recipient_ids.update(
            User.objects.filter(
                is_active=True,
                role=UserRole.PARENT,
                parent_profile__students__in=visible,
            ).values_list("id", flat=True)
        )

    recipient_ids.discard(actor.pk)

    return recipient_ids


def send_notification(
    *,
    actor,
    title: str,
    message: str = "",
    to_school_admins: bool = False,
    to_teachers: bool = False,
    to_parents: bool = False,
    schools: list | None = None,
    class_sections: list | None = None,
    users: list | None = None,
    students: list | None = None,
    attachments: list | None = None,
) -> Notification:
    schools = schools or []
    class_sections = class_sections or []
    users = users or []
    students = students or []
    attachments = attachments or []

    if not message.strip() and not attachments:
        raise ValidationError({"message": "Write a message or attach at least one file."})

    validate_attachments(attachments)

    audience = {
        "to_school_admins": to_school_admins,
        "to_teachers": to_teachers,
        "to_parents": to_parents,
    }

    recipient_ids = resolve_recipient_ids(
        actor=actor,
        audience=audience,
        schools=schools,
        class_sections=class_sections,
        users=users,
        students=students,
    )

    if not recipient_ids:
        raise ValidationError({"detail": "Nobody matches the chosen audience."})

    role = sender_role(actor)

    with transaction.atomic():
        notification = Notification.objects.create(
            title=title,
            message=message,
            created_by=actor,
            sender_role=role,
            school=None if role == UserRole.SUPER_ADMIN else sender_school(actor),
            recipient_count=len(recipient_ids),
            **audience,
        )

        notification.target_schools.set(schools)
        notification.target_class_sections.set(class_sections)
        notification.target_users.set(users)
        notification.target_students.set(students)

        _save_attachments(notification, attachments)

        NotificationRecipient.objects.bulk_create(
            [
                NotificationRecipient(notification=notification, user_id=user_id)
                for user_id in recipient_ids
            ],
            batch_size=1000,
        )

    send_push(
        recipient_ids,
        title=title,
        body=message or "Open SmartPresence to read it.",
        path="inbox",
        tag=f"notification-{notification.pk}",
    )

    logger.info(
        "Notification %s sent by user %s to %s recipient(s)",
        notification.pk,
        actor.pk,
        len(recipient_ids),
    )

    return notification


@transaction.atomic
def delete_notification(*, notification: Notification) -> None:
    """
    Withdraw a notification from every inbox and delete its files.
    """

    files = [attachment.file for attachment in notification.attachments.all()]

    notification.delete()

    for file_field in files:
        transaction.on_commit(lambda f=file_field: f.delete(save=False))


def mark_read(*, user, ids: list[int] | None = None) -> int:
    """
    Mark inbox items read; ``ids`` are notification IDs, or None for all.
    """

    queryset = NotificationRecipient.objects.filter(user=user, is_read=False)

    if ids is not None:
        queryset = queryset.filter(notification_id__in=ids)

    return queryset.update(is_read=True, read_at=timezone.now())
