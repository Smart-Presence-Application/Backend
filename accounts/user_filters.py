import django_filters

from accounts.models import User


class UserFilter(django_filters.FilterSet):
    joined_after = django_filters.DateFilter(
        field_name="date_joined",
        lookup_expr="gte"
    )

    joined_before = django_filters.DateFilter(
        field_name="date_joined",
        lookup_expr="lte"
    )

    last_login_after = django_filters.DateFilter(
        field_name="last_login",
        lookup_expr="gte"
    )

    last_login_before = django_filters.DateFilter(
        field_name="last_login",
        lookup_expr="lte"
    )

    class Meta:
        model = User
        fields = [
            "is_active",
            "is_staff",
            "is_superuser",
            "role",
        ]