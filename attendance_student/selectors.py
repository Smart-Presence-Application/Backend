from django.db.models import Prefetch, QuerySet

from common.ordering import roll_order

from students.selectors import (
    get_actor_class_section,
    get_students_visible_to,
    is_school_admin,
    is_super_admin,
    is_teacher,
)

from .models import AttendanceRecord, AttendanceSession


def is_attendance_admin(actor) -> bool:
    """
    Admins may edit attendance at any time, locked or not.
    """

    return is_super_admin(actor) or is_school_admin(actor)


def get_session_queryset() -> QuerySet[AttendanceSession]:
    return AttendanceSession.objects.select_related(
        "school",
        "class_section",
        "class_section__academic_year",
        "class_section__school_class",
        "class_section__section",
        "created_by",
        "locked_by",
    )


def get_sessions_visible_to(actor) -> QuerySet[AttendanceSession]:
    """
    Sessions the actor may read.

    Same scope as students: everything for a Super Admin, one school
    for a School Admin, and only the currently assigned class-section
    for a teacher.
    """

    queryset = get_session_queryset()

    if is_super_admin(actor):
        return queryset

    if is_school_admin(actor):
        school = getattr(actor, "managed_school", None)

        if school is None:
            return queryset.none()

        return queryset.filter(school=school)

    if is_teacher(actor):
        class_section = get_actor_class_section(actor)

        if class_section is None:
            return queryset.none()

        return queryset.filter(class_section=class_section)

    return queryset.none()


def get_session(pk: int, *, actor, with_records: bool = False):
    queryset = get_sessions_visible_to(actor)

    if with_records:
        queryset = queryset.prefetch_related(
            Prefetch(
                "records",
                queryset=AttendanceRecord.objects.select_related(
                    "student",
                    "updated_by",
                ).order_by(roll_order("student__roll_number")),
            )
        )

    return queryset.filter(pk=pk).first()


def get_face_students_visible_to(actor) -> QuerySet:
    """
    Students whose face the actor may register or delete.
    """

    return get_students_visible_to(actor).select_related("face_registration")
