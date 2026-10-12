from django.db.models import QuerySet

from academics.models import ClassSection
from common.choices import UserRole

from .models import Student


def is_super_admin(actor) -> bool:
    return bool(
        actor
        and (
            actor.is_superuser
            or actor.role == UserRole.SUPER_ADMIN
        )
    )


def is_school_admin(actor) -> bool:
    return bool(
        actor
        and actor.role == UserRole.SCHOOL_ADMIN
    )


def is_teacher(actor) -> bool:
    return bool(
        actor
        and actor.role == UserRole.TEACHER
    )


def get_actor_class_section(actor) -> ClassSection | None:
    """
    The class-section a teacher is assigned to, if any.

    Returns None for anyone who is not a teacher, and for a teacher
    without a profile or without an assignment.
    """

    profile = getattr(actor, "teacher_profile", None)

    if profile is None:
        return None

    return profile.class_section


def get_student_queryset() -> QuerySet[Student]:
    """Students with their relations loaded, including the reverse face registration so lists need no query per row."""
    return Student.objects.select_related(
        "school",
        "class_section",
        "class_section__academic_year",
        "class_section__school_class",
        "class_section__section",
        "face_registration",
    )


def get_students_visible_to(actor) -> QuerySet[Student]:
    """
    Students the actor may read and manage.

    Super admins see every student, school admins see their own
    school's, and a teacher sees only the students of the class-section
    they are assigned to. A teacher with no assignment sees none.
    """

    if is_super_admin(actor):
        return get_student_queryset()

    if is_school_admin(actor):
        school = getattr(actor, "managed_school", None)

        if school is None:
            return Student.objects.none()

        return get_student_queryset().filter(school=school)

    if is_teacher(actor):
        class_section = get_actor_class_section(actor)

        if class_section is None:
            return Student.objects.none()

        return get_student_queryset().filter(
            class_section=class_section,
        )

    return Student.objects.none()


def get_student(pk: int, *, actor) -> Student | None:
    return get_students_visible_to(actor).filter(pk=pk).first()


def get_class_sections_visible_to(actor) -> QuerySet[ClassSection]:
    """
    Class-sections the actor may place a student into.

    This is the same scope as the student queryset, expressed over
    class-sections, so a caller can never move a student somewhere they
    would immediately lose sight of them.
    """

    queryset = ClassSection.objects.select_related(
        "academic_year",
        "school_class",
        "section",
    )

    if is_super_admin(actor):
        return queryset

    if is_school_admin(actor):
        school = getattr(actor, "managed_school", None)

        if school is None:
            return queryset.none()

        return queryset.filter(academic_year__school=school)

    if is_teacher(actor):
        class_section = get_actor_class_section(actor)

        if class_section is None:
            return queryset.none()

        return queryset.filter(pk=class_section.pk)

    return queryset.none()
