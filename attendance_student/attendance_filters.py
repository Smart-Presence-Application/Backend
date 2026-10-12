import django_filters

from .models import AttendanceSession, SessionStatus


class AttendanceSessionFilter(django_filters.FilterSet):
    """
    Filters for AttendanceSession.

    These narrow whatever the caller can already see; they never widen
    it.
    """

    school = django_filters.NumberFilter(
        field_name="school_id",
    )
    class_section = django_filters.NumberFilter(
        field_name="class_section_id",
    )
    academic_year = django_filters.NumberFilter(
        field_name="class_section__academic_year_id",
    )
    date = django_filters.DateFilter(
        field_name="date",
    )
    date_from = django_filters.DateFilter(
        field_name="date",
        lookup_expr="gte",
    )
    date_to = django_filters.DateFilter(
        field_name="date",
        lookup_expr="lte",
    )
    status = django_filters.ChoiceFilter(
        choices=SessionStatus.choices,
    )

    class Meta:
        model = AttendanceSession
        fields = [
            "school",
            "class_section",
            "academic_year",
            "date",
            "date_from",
            "date_to",
            "status",
        ]
