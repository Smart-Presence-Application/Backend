import django_filters

from .models import (
    AcademicYear,
    ClassSection,
    Holiday,
    SchoolClass,
    Section,
    WorkingDay,
)


class AcademicYearFilter(django_filters.FilterSet):
    """Filters for AcademicYear."""

    class Meta:
        model = AcademicYear
        fields = {
            "school": ["exact"],
            "is_active": ["exact"],
            "start_date": ["exact", "gte", "lte"],
            "end_date": ["exact", "gte", "lte"],
        }


class SchoolClassFilter(django_filters.FilterSet):
    """Filters for SchoolClass."""

    class Meta:
        model = SchoolClass
        fields = {
            "school": ["exact"],
        }


class SectionFilter(django_filters.FilterSet):
    """Filters for Section."""

    class Meta:
        model = Section
        fields = {
            "school": ["exact"],
        }


class ClassSectionFilter(django_filters.FilterSet):
    """Filters for ClassSection."""

    class Meta:
        model = ClassSection
        fields = {
            "academic_year": ["exact"],
            "school_class": ["exact"],
            "section": ["exact"],
        }


class HolidayFilter(django_filters.FilterSet):
    """
    Filters for Holiday.

    Supported query parameters:

        academic_year
        month
        date
        date__gte
        date__lte
    """

    month = django_filters.NumberFilter(
        field_name="date",
        lookup_expr="month",
    )

    class Meta:
        model = Holiday
        fields = {
            "academic_year": ["exact"],
            "date": ["exact", "gte", "lte"],
        }


class WorkingDayFilter(django_filters.FilterSet):
    """
    Filters for WorkingDay.

    Supported query parameters:

        academic_year
        month
        date
        day_type
    """

    month = django_filters.NumberFilter(
        field_name="date",
        lookup_expr="month",
    )

    class Meta:
        model = WorkingDay
        fields = {
            "academic_year": ["exact"],
            "date": ["exact", "gte", "lte"],
            "day_type": ["exact"],
        }