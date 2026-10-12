import django_filters

from .models import Teacher


class TeacherFilter(django_filters.FilterSet):
    """Filters for Teacher."""

    school = django_filters.NumberFilter(
        field_name="school_id",
    )
    class_section = django_filters.NumberFilter(
        field_name="class_section_id",
    )
    is_active = django_filters.BooleanFilter(
        field_name="user__is_active",
    )
    is_assigned = django_filters.BooleanFilter(
        field_name="class_section_id",
        lookup_expr="isnull",
        exclude=True,
    )
    city = django_filters.CharFilter(
        field_name="city",
        lookup_expr="iexact",
    )
    state = django_filters.CharFilter(
        field_name="state",
        lookup_expr="iexact",
    )
    joined_after = django_filters.DateFilter(
        field_name="joining_date",
        lookup_expr="gte",
    )
    joined_before = django_filters.DateFilter(
        field_name="joining_date",
        lookup_expr="lte",
    )

    class Meta:
        model = Teacher
        fields = [
            "school",
            "class_section",
            "is_active",
            "is_assigned",
            "city",
            "state",
        ]
