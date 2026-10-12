from django.core.exceptions import ValidationError

from accounts.models import User

from .selectors import get_existing_employee_ids


def validate_employee_id_available(
    *,
    school_id: int,
    employee_id: str,
    instance=None,
) -> None:
    """Employee ids are unique within a school."""

    queryset = get_existing_employee_ids(
        school_id=school_id,
        employee_ids=[employee_id],
    )

    if not queryset:
        return

    if instance is not None and instance.employee_id == employee_id:
        return

    raise ValidationError(
        {
            "employee_id": (
                "A teacher with this employee ID already exists "
                "in this school."
            )
        }
    )


def validate_email_available(
    *,
    email: str,
    instance=None,
) -> None:
    """Logins are unique across the whole system, not just one school."""

    queryset = User.objects.filter(email__iexact=email)

    if instance is not None:
        queryset = queryset.exclude(pk=instance.user_id)

    if queryset.exists():
        raise ValidationError(
            {
                "email": (
                    "A user with this email address already exists."
                )
            }
        )


def validate_class_section_school(
    *,
    class_section,
    school_id: int,
) -> None:
    """A teacher can only be assigned within their own school."""

    if class_section.academic_year.school_id != school_id:
        raise ValidationError(
            {
                "class_section": (
                    "The class section does not belong to this "
                    "teacher's school."
                )
            }
        )
