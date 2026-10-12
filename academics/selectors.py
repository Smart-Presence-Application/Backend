from datetime import date

from django.db.models import QuerySet

from .models import (
    AcademicYear,
    SchoolClass,
    Section,
    ClassSection,
    Holiday,
    WorkingDay,
)


def get_working_days_for_dates(
    *,
    school_id: int,
    dates,
) -> QuerySet[WorkingDay]:
    """Return a school's working-day records for a specific set of dates."""

    return WorkingDay.objects.filter(
        school_id=school_id,
        date__in=dates,
    )


def get_academic_year_queryset(
    school=None,
) -> QuerySet[AcademicYear]:
    queryset = AcademicYear.objects.select_related("school")

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset


def get_school_class_queryset(
    school=None,
) -> QuerySet[SchoolClass]:
    queryset = SchoolClass.objects.select_related("school")

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset


def get_section_queryset(
    school=None,
) -> QuerySet[Section]:
    queryset = Section.objects.select_related("school")

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset


def get_class_section_queryset(
    school=None,
) -> QuerySet[ClassSection]:
    queryset = ClassSection.objects.select_related(
        "academic_year",
        "academic_year__school",
        "school_class",
        "section",
    )

    if school is not None:
        queryset = queryset.filter(
            academic_year__school=school,
        )

    return queryset


def get_holiday_queryset(
    school=None,
) -> QuerySet[Holiday]:
    queryset = Holiday.objects.select_related(
        "school",
        "academic_year",
    )

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset


def get_working_day_queryset(
    school=None,
) -> QuerySet[WorkingDay]:
    queryset = WorkingDay.objects.select_related(
        "school",
        "academic_year",
    )

    if school is not None:
        queryset = queryset.filter(school=school)

    return queryset


def get_academic_year_overlap_queryset(
    *,
    school_id: int,
    start_date: date,
    end_date: date,
):
    return AcademicYear.objects.filter(
        school_id=school_id,
        start_date__lte=end_date,
        end_date__gte=start_date,
    )