from datetime import date

from django.core.exceptions import ValidationError

from .models import AcademicYear
from .selectors import get_academic_year_overlap_queryset


def validate_academic_year_dates(
    *,
    start_date: date,
    end_date: date,
) -> None:
    if end_date <= start_date:
        raise ValidationError(
            {
                "end_date": (
                    "End date must be greater than start date."
                )
            }
        )


def validate_academic_year_overlap(
    *,
    school_id: int,
    start_date: date,
    end_date: date,
    instance: AcademicYear | None = None,
) -> None:
    validate_academic_year_dates(
        start_date=start_date,
        end_date=end_date,
    )

    queryset = get_academic_year_overlap_queryset(
        school_id=school_id,
        start_date=start_date,
        end_date=end_date,
    )

    if instance is not None:
        queryset = queryset.exclude(pk=instance.pk)

    if queryset.exists():
        message = (
            "The academic year overlaps with an existing "
            "academic year for this school."
        )

        raise ValidationError(
            {
                "start_date": message,
                "end_date": message,
            }
        )


def validate_academic_year_school(
    *,
    academic_year: AcademicYear,
    school_id: int,
) -> None:
    if academic_year.school_id != school_id:
        raise ValidationError(
            {
                "academic_year": (
                    "The academic year does not belong to this school."
                )
            }
        )
        
        
def validate_date_in_academic_year(
    *,
    academic_year: AcademicYear,
    target_date: date,
    field_name: str = "date",
) -> None:
    if not (
        academic_year.start_date
        <= target_date
        <= academic_year.end_date
    ):
        raise ValidationError(
            {
                field_name: (
                    "Date must fall within the academic year."
                )
            }
        )
        

def validate_school_ownership(
    *,
    object_name: str,
    actual_school_id: int,
    expected_school_id: int,
    field_name: str,
) -> None:
    if actual_school_id != expected_school_id:
        raise ValidationError(
            {
                field_name: (
                    f"The {object_name} does not belong to this school."
                )
            }
        )
        
        
def validate_same_school(
    *,
    academic_year: AcademicYear,
    school_class,
    section,
) -> None:
    if academic_year.school_id != school_class.school_id:
        raise ValidationError(
            {
                "school_class": (
                    "The class must belong to the same school "
                    "as the academic year."
                )
            }
        )

    if academic_year.school_id != section.school_id:
        raise ValidationError(
            {
                "section": (
                    "The section must belong to the same school "
                    "as the academic year."
                )
            }
        )
        
        
def validate_authorized_school(
    *,
    authorized_school,
    academic_year=None,
    school_class=None,
    section=None,
) -> None:
    if (
        academic_year is not None
        and academic_year.school_id != authorized_school.id
    ):
        raise ValidationError(
            {
                "academic_year": (
                    "The academic year does not belong to the authorized school."
                )
            }
        )

    if (
        school_class is not None
        and school_class.school_id != authorized_school.id
    ):
        raise ValidationError(
            {
                "school_class": (
                    "The class does not belong to the authorized school."
                )
            }
        )

    if (
        section is not None
        and section.school_id != authorized_school.id
    ):
        raise ValidationError(
            {
                "section": (
                    "The section does not belong to the authorized school."
                )
            }
        )
        