from django.core.exceptions import ValidationError

from .models import Student


def validate_class_section_school(
    *,
    class_section,
    school,
) -> None:
    """
    The class-section must sit inside the school it is claimed for.

    Super Admins pass both, so this catches a mismatched pair before
    anything is written.
    """

    if class_section.academic_year.school_id != school.id:
        raise ValidationError(
            {
                "class_section": (
                    "The class section does not belong to the "
                    "selected school."
                )
            }
        )


def validate_student_id_available(
    *,
    school_id: int,
    student_id: str,
    instance=None,
) -> None:
    """Student IDs are unique within a school."""

    queryset = Student.objects.filter(
        school_id=school_id,
        student_id=student_id,
    )

    if instance is not None:
        queryset = queryset.exclude(pk=instance.pk)

    if queryset.exists():
        raise ValidationError(
            {
                "student_id": (
                    "A student with this student ID already exists "
                    "in this school."
                )
            }
        )


def validate_roll_number_available(
    *,
    class_section_id: int,
    roll_number: str,
    instance=None,
) -> None:
    """Roll numbers are unique within a class-section."""

    queryset = Student.objects.filter(
        class_section_id=class_section_id,
        roll_number=roll_number,
    )

    if instance is not None:
        queryset = queryset.exclude(pk=instance.pk)

    if queryset.exists():
        raise ValidationError(
            {
                "roll_number": (
                    "A student with this roll number already exists "
                    "in this class section."
                )
            }
        )
