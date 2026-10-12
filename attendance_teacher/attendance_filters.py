import django_filters

from .models import TeacherAttendance, TeacherAttendanceStatus, WorkDayType


class TeacherAttendanceFilter(django_filters.FilterSet):
    """
    Filters for TeacherAttendance.

    These narrow whatever the caller can already see; they never widen
    it.
    """

    school = django_filters.NumberFilter(
        field_name="school_id",
    )
    teacher = django_filters.NumberFilter(
        field_name="teacher_id",
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
        choices=TeacherAttendanceStatus.choices,
    )
    day_type = django_filters.ChoiceFilter(
        choices=WorkDayType.choices,
    )

    class Meta:
        model = TeacherAttendance
        fields = [
            "school",
            "teacher",
            "date",
            "date_from",
            "date_to",
            "status",
            "day_type",
        ]
