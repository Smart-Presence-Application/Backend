import django_filters

from common.choices import UserRole

from .models import ActivityLog


class ActivityLogFilter(django_filters.FilterSet):
    actor = django_filters.NumberFilter(field_name="actor_id")
    school = django_filters.NumberFilter(field_name="school_id")
    role = django_filters.ChoiceFilter(field_name="actor_role", choices=UserRole.choices)
    category = django_filters.CharFilter(field_name="category")
    method = django_filters.CharFilter(field_name="method", lookup_expr="iexact")
    outcome = django_filters.ChoiceFilter(
        method="filter_outcome",
        choices=[("success", "Succeeded"), ("failed", "Failed")],
    )
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = ActivityLog
        fields = ["actor", "school", "role", "category", "method", "outcome", "date_from", "date_to"]

    def filter_outcome(self, queryset, name, value):
        return queryset.filter(status_code__lt=400) if value == "success" else queryset.filter(status_code__gte=400)
