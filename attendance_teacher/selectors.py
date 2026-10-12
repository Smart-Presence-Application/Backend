from django.db.models import QuerySet

from students.selectors import is_school_admin, is_super_admin, is_teacher

from .models import TeacherAttendance


def get_attendance_queryset() -> QuerySet[TeacherAttendance]:
    return TeacherAttendance.objects.select_related(
        "teacher",
        "teacher__user",
        "school",
        "verified_by",
    )


def get_attendance_visible_to(actor) -> QuerySet[TeacherAttendance]:
    """
    Super Admins see every school, School Admins their own school, and
    a teacher only their own days.
    """

    queryset = get_attendance_queryset()

    if is_super_admin(actor):
        return queryset

    if is_school_admin(actor):
        school = getattr(actor, "managed_school", None)

        if school is None:
            return queryset.none()

        return queryset.filter(school=school)

    if is_teacher(actor):
        teacher = getattr(actor, "teacher_profile", None)

        if teacher is None:
            return queryset.none()

        return queryset.filter(teacher=teacher)

    return queryset.none()
