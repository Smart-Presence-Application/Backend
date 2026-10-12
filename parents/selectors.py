"""
Parent selectors.

CHILD_SORT_FIELDS orders parents by their first child: class, section, then
roll number (see Student.Meta.ordering).
"""
from django.db.models import OuterRef, Prefetch, QuerySet, Subquery

from attendance_student.models import AttendanceRecord, SessionStatus
from common.ordering import roll_order
from students.selectors import (
    get_actor_class_section,
    get_student_queryset,
    get_students_visible_to,
    is_school_admin,
    is_super_admin,
    is_teacher,
)

from .models import Parent, ParentNotification

CHILD_SORT_FIELDS = {
    "child_year": "class_section__academic_year__start_date",
    "child_class": "class_section__school_class__name",
    "child_section": "class_section__section__name",
    "roll_number": "roll_number",
}
PARENT_ORDERING = [*CHILD_SORT_FIELDS, "user__name"]


def with_child_order(queryset: QuerySet[Parent], visible_students) -> QuerySet[Parent]:
    """
    Annotate each parent with the class and roll number of their first
    child in scope, so the list can follow roll-number order.
    """

    first_child = visible_students.filter(parents=OuterRef("pk")).order_by(
        "class_section__academic_year__start_date",
        "class_section__school_class__name",
        "class_section__section__name",
        roll_order(),
    )

    return queryset.annotate(
        **{
            name: Subquery(first_child.values(field)[:1])
            for name, field in CHILD_SORT_FIELDS.items()
        }
    )


def get_parents_visible_to(actor) -> QuerySet[Parent]:
    """
    Parents the actor may read and manage: those with at least one
    child the actor can see. Each parent's ``students`` are prefetched
    narrowed to that same scope, so a teacher never sees siblings in
    other sections.
    """

    visible_students = get_students_visible_to(actor)

    if is_super_admin(actor):
        queryset = Parent.objects.all()
    elif is_school_admin(actor):
        school = getattr(actor, "managed_school", None)

        if school is None:
            return Parent.objects.none()

        queryset = Parent.objects.filter(students__school=school)
    elif is_teacher(actor):
        class_section = get_actor_class_section(actor)

        if class_section is None:
            return Parent.objects.none()

        queryset = Parent.objects.filter(students__class_section=class_section)
    else:
        return Parent.objects.none()

    return (
        with_child_order(queryset.distinct(), visible_students)
        .select_related("user", "created_by")
        .prefetch_related(Prefetch("students", queryset=visible_students))
    )


def get_parent(pk: int, *, actor) -> Parent | None:
    return get_parents_visible_to(actor).filter(pk=pk).first()


def get_own_parent(user) -> Parent | None:
    return (
        Parent.objects.select_related("user")
        .prefetch_related(Prefetch("students", queryset=get_student_queryset()))
        .filter(user=user)
        .first()
    )


def get_children_attendance(parent: Parent) -> QuerySet[AttendanceRecord]:
    """
    Final (locked) attendance of the parent's children.

    Drafts are left out: the teacher may still correct them, and a
    parent should only see what the school has confirmed.
    """

    return (
        AttendanceRecord.objects.filter(
            student__parents=parent,
            session__status=SessionStatus.LOCKED,
        )
        .select_related(
            "student",
            "session",
            "session__class_section__school_class",
            "session__class_section__section",
        )
        .order_by("-session__date", "student__name")
    )


def get_notifications(parent: Parent) -> QuerySet[ParentNotification]:
    return parent.notifications.select_related("student")
