from django.db.models import QuerySet

from common.choices import UserRole

from .models import Teacher


def is_global_teacher_admin(actor) -> bool:
    """Super admins act across every school; school admins do not."""

    return bool(
        actor
        and (
            actor.is_superuser
            or actor.role == UserRole.SUPER_ADMIN
        )
    )


def get_teacher_queryset(school=None) -> QuerySet[Teacher]:
    queryset = Teacher.objects.select_related(
        "user",
        "school",
        "class_section",
        "class_section__academic_year",
        "class_section__school_class",
        "class_section__section",
    )

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset


def get_teachers_visible_to(actor) -> QuerySet[Teacher]:
    """
    Teachers the actor is allowed to read and manage.

    Super admins see every teacher. School admins see only the teachers
    of the school they manage. Anyone else sees none.
    """

    if is_global_teacher_admin(actor):
        return get_teacher_queryset()

    school = getattr(actor, "managed_school", None)

    if school is None:
        return Teacher.objects.none()

    return get_teacher_queryset(school)


def get_teacher(pk: int, *, actor=None) -> Teacher | None:
    queryset = (
        get_teacher_queryset()
        if actor is None
        else get_teachers_visible_to(actor)
    )

    return queryset.filter(pk=pk).first()


def get_teacher_profile(user) -> Teacher | None:
    """Return the teacher profile belonging to a user, if any."""

    return (
        get_teacher_queryset()
        .filter(user=user)
        .first()
    )


def get_existing_employee_ids(
    *,
    school_id: int,
    employee_ids,
) -> set[str]:
    """Return the employee ids already taken within a school."""

    return set(
        Teacher.objects.filter(
            school_id=school_id,
            employee_id__in=employee_ids,
        ).values_list("employee_id", flat=True)
    )
