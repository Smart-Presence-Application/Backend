import django_filters
from django.db.models import Q

from .models import School


class SchoolFilter(django_filters.FilterSet):
    search = django_filters.CharFilter(method="filter_search")

    city = django_filters.CharFilter(
        field_name="city",
        lookup_expr="icontains",
    )

    state = django_filters.CharFilter(
        field_name="state",
        lookup_expr="icontains",
    )

    ordering = django_filters.OrderingFilter(
        fields=(
            ("name", "name"),
            ("code", "code"),
            ("city", "city"),
            ("state", "state"),
            ("created_at", "created_at"),
            ("updated_at", "updated_at"),
        )
    )

    class Meta:
        model = School
        fields = (
            "status",
            "city",
            "state",
        )

    def filter_search(self, queryset, name, value):
        return queryset.filter(
            Q(name__icontains=value)
            | Q(code__icontains=value)
            | Q(email__icontains=value)
            | Q(phone__icontains=value)
        )