"""
Student filters.

A missing image is stored either as NULL or as an empty string depending
on how it was written, so NO_IMAGE treats both as "no image".
"""
import django_filters
from django.db.models import Q

from .models import Student

NO_IMAGE = Q(profile_image="") | Q(profile_image__isnull=True)


class StudentFilter(django_filters.FilterSet):
    """
    Filters for Student.

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
    school_class = django_filters.NumberFilter(
        field_name="class_section__school_class_id",
    )
    section = django_filters.NumberFilter(
        field_name="class_section__section_id",
    )
    has_profile_image = django_filters.BooleanFilter(
        method="filter_has_profile_image",
    )
    face_registered = django_filters.BooleanFilter(
        field_name="face_registration",
        lookup_expr="isnull",
        exclude=True,
    )

    class Meta:
        model = Student
        fields = [
            "school",
            "class_section",
            "academic_year",
            "school_class",
            "section",
            "has_profile_image",
            "face_registered",
        ]

    def filter_has_profile_image(self, queryset, name, value):
        """Split students by whether an embedding can be built for them."""

        if value:
            return queryset.exclude(NO_IMAGE)

        return queryset.filter(NO_IMAGE)
