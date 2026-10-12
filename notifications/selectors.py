"""
Who may send to whom, and who receives what.

A sender's *pool* is every user they are allowed to reach:

* Super Admin  -> School Admins, teachers and parents of any school
* School Admin -> teachers and parents of their own school
* Teacher      -> parents of their own class-section's students

Role-wide audiences and individually chosen recipients must both come
from that pool. ``ALLOWED_AUDIENCES`` lists the roles each sender role
may address as a whole.
"""

from django.db.models import Count, Max, Prefetch, Q, QuerySet

from accounts.models import User
from common.choices import UserRole
from schools.models import School
from students.selectors import (
    get_actor_class_section,
    is_school_admin,
    is_super_admin,
    is_teacher,
)

from .models import Notification, NotificationRecipient

ALLOWED_AUDIENCES = {
    UserRole.SUPER_ADMIN: {"to_school_admins", "to_teachers", "to_parents"},
    UserRole.SCHOOL_ADMIN: {"to_teachers", "to_parents"},
    UserRole.TEACHER: {"to_parents"},
}


def sender_role(actor) -> str | None:
    if is_super_admin(actor):
        return UserRole.SUPER_ADMIN

    if is_school_admin(actor):
        return UserRole.SCHOOL_ADMIN

    if is_teacher(actor):
        return UserRole.TEACHER

    return None


def active_users() -> QuerySet[User]:
    return User.objects.filter(is_active=True)


def school_admin_users(schools) -> QuerySet[User]:
    return active_users().filter(
        role=UserRole.SCHOOL_ADMIN,
        managed_school__in=schools,
    )


def teacher_users(schools, class_sections=None) -> QuerySet[User]:
    queryset = active_users().filter(
        role=UserRole.TEACHER,
        teacher_profile__school__in=schools,
    )

    if class_sections is not None:
        queryset = queryset.filter(teacher_profile__class_section__in=class_sections)

    return queryset


def parent_users(schools, class_sections=None) -> QuerySet[User]:
    queryset = active_users().filter(
        role=UserRole.PARENT,
        parent_profile__students__school__in=schools,
    )

    if class_sections is not None:
        queryset = queryset.filter(
            parent_profile__students__class_section__in=class_sections,
        )

    return queryset


def sender_school(actor) -> School | None:
    """
    The school a School Admin or teacher sends on behalf of.
    """

    if is_school_admin(actor):
        return getattr(actor, "managed_school", None)

    if is_teacher(actor):
        profile = getattr(actor, "teacher_profile", None)
        return profile.school if profile else None

    return None


def get_sender_pool(actor) -> QuerySet[User]:
    """
    Every user ``actor`` may send a notification to.
    """

    role = sender_role(actor)

    if role == UserRole.SUPER_ADMIN:
        return active_users().filter(
            role__in=[UserRole.SCHOOL_ADMIN, UserRole.TEACHER, UserRole.PARENT],
        )

    if role == UserRole.SCHOOL_ADMIN:
        school = sender_school(actor)

        if school is None:
            return User.objects.none()

        return active_users().filter(
            Q(role=UserRole.TEACHER, teacher_profile__school=school)
            | Q(role=UserRole.PARENT, parent_profile__students__school=school)
        ).distinct()

    if role == UserRole.TEACHER:
        class_section = get_actor_class_section(actor)

        if class_section is None:
            return User.objects.none()

        return parent_users([class_section.academic_year.school], [class_section]).distinct()

    return User.objects.none()


def get_inbox(user) -> QuerySet[NotificationRecipient]:
    return (
        NotificationRecipient.objects.filter(user=user)
        .select_related("notification", "notification__created_by", "notification__school")
        .prefetch_related("notification__attachments")
    )


def get_sent_by(actor) -> QuerySet[Notification]:
    """
    Notifications the actor sent, with delivery counts.

    School Admins also see what their teachers sent, so they can review
    (and remove) anything that went to their school's parents. Super
    Admins see every notification. Ordered explicitly because
    ``Meta.ordering`` is dropped on aggregated queries.
    """

    queryset = Notification.objects.select_related("created_by", "school").prefetch_related(
        "attachments",
        "target_schools",
        "target_class_sections",
        Prefetch("target_users", queryset=User.objects.only("id", "name", "role")),
        "target_students",
    )

    if is_school_admin(actor):
        school = sender_school(actor)
        queryset = queryset.filter(Q(created_by=actor) | Q(school=school, school__isnull=False))
    elif not is_super_admin(actor):
        queryset = queryset.filter(created_by=actor)

    return queryset.annotate(
        read_count=Count("recipients", filter=Q(recipients__is_read=True)),
        last_read_at=Max("recipients__read_at"),
    ).order_by("-created_at")


def get_read_summary(notification: Notification) -> list[dict]:
    """
    Seen / not seen counts per recipient role, e.g. 30 of 42 parents.
    """

    rows = (
        notification.recipients.values("user__role")
        .annotate(
            total=Count("id"),
            seen=Count("id", filter=Q(is_read=True)),
        )
        .order_by("user__role")
    )

    return [
        {
            "role": row["user__role"],
            "total": row["total"],
            "seen": row["seen"],
            "not_seen": row["total"] - row["seen"],
        }
        for row in rows
    ]


def can_delete(actor, notification: Notification) -> bool:
    if is_super_admin(actor) or notification.created_by_id == actor.pk:
        return True

    return bool(
        is_school_admin(actor)
        and notification.school_id is not None
        and notification.school_id == getattr(sender_school(actor), "id", None)
    )
