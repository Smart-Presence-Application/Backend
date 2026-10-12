from rest_framework import serializers
from schools.models import School
from common.choices import UserRole, Weekday
from .models import (
AcademicYear,
SchoolClass,
ClassSection,
Section,
Holiday,
WorkingDay,
)


class SchoolScopedCreateSerializerMixin:
    """
    Makes the school field mandatory only for Super Admins.

    For School Admins, school is removed from the request fields because
    it is assigned automatically by the view.
    """

    def get_fields(self):
        fields = super().get_fields()

        request = self.context.get("request")

        if request is None or not request.user.is_authenticated:
            return fields

        if request.user.role != UserRole.SUPER_ADMIN:
            fields.pop("school", None)

        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)

        request = self.context.get("request")

        if request is None:
            return attrs

        if (
            request.user.role == UserRole.SUPER_ADMIN
            and attrs.get("school") is None
        ):
            raise serializers.ValidationError(
                {
                    "school": (
                        "This field is required when creating data "
                        "as a Super Admin."
                    )
                }
            )

        return attrs

class SchoolPrimaryKeyRelatedField(
    serializers.PrimaryKeyRelatedField
):
    """
    Super Admins can select any school.

    School Admins do not need to submit a school.
    """

    def get_queryset(self):
        request = self.context.get("request")

        queryset = School.objects.all()

        if not request or not request.user.is_authenticated:
            return queryset.none()

        if request.user.role == UserRole.SCHOOL_ADMIN:
            return queryset.filter(
                admin=request.user,
            )

        return queryset
        

class AcademicYearListSerializer(serializers.ModelSerializer):
    """Serializer used for listing academic years."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )

    class Meta:
        model = AcademicYear
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "start_date",
            "end_date",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "is_active",
            "created_at",
            "updated_at",
        ]


class AcademicYearDetailSerializer(serializers.ModelSerializer):
    """Serializer used for retrieving an academic year."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )

    class Meta:
        model = AcademicYear
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "start_date",
            "end_date",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "is_active",
            "created_at",
            "updated_at",
        ]

class AcademicYearCreateSerializer(
    SchoolScopedCreateSerializerMixin,
    serializers.ModelSerializer,
):
    school = SchoolPrimaryKeyRelatedField(
        queryset=School.objects.none(),
        required=False,
    )

    class Meta:
        model = AcademicYear
        fields = [
            "school",
            "name",
            "start_date",
            "end_date",
        ]


class AcademicYearUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer used to update an academic year.

    Activation is intentionally handled by the dedicated activation
    service/endpoint instead of allowing arbitrary updates to change
    the active status.
    """

    class Meta:
        model = AcademicYear
        fields = [
            "name",
            "start_date",
            "end_date",
        ]


class SchoolClassListSerializer(serializers.ModelSerializer):
    """Serializer used for listing school classes."""
    

    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )

    class Meta:
        model = SchoolClass
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "created_at",
            "updated_at",
        ]


class SchoolClassDetailSerializer(serializers.ModelSerializer):
    """Serializer used for retrieving a school class."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )

    class Meta:
        model = SchoolClass
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "created_at",
            "updated_at",
        ]


class SchoolClassCreateSerializer(
    SchoolScopedCreateSerializerMixin,
    serializers.ModelSerializer,
):
    """Serializer used to create a school class."""

    school = SchoolPrimaryKeyRelatedField(
        queryset=School.objects.none(),
        required=False,
    )

    class Meta:
        model = SchoolClass
        fields = [
            "school",
            "name",
        ]

    def validate_name(self, value):
        return value.strip()


class SchoolClassUpdateSerializer(serializers.ModelSerializer):
    """Serializer used to update a school class."""


    class Meta:
        model = SchoolClass
        fields = [
            "name",
        ]

    def validate_name(self, value):
        return value.strip()


class SectionListSerializer(serializers.ModelSerializer):
    """Serializer used for listing sections."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )

    class Meta:
        model = Section
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "created_at",
            "updated_at",
        ]


class SectionDetailSerializer(serializers.ModelSerializer):
    """Serializer used for retrieving a section."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )

    class Meta:
        model = Section
        fields = [
            "id",
            "school",
            "school_name",
            "name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "created_at",
            "updated_at",
        ]


class SectionCreateSerializer(
    SchoolScopedCreateSerializerMixin,
    serializers.ModelSerializer,
):
    """Serializer used to create a section."""

    school = SchoolPrimaryKeyRelatedField(
        queryset=School.objects.none(),
        required=False,
    )

    class Meta:
        model = Section
        fields = [
            "school",
            "name",
        ]

    def validate_name(self, value):
        return value.strip()


class SectionUpdateSerializer(serializers.ModelSerializer):
    """Serializer used to update a section."""


    class Meta:
        model = Section
        fields = [
            "name",
        ]

    def validate_name(self, value):
        return value.strip()


class ClassSectionListSerializer(serializers.ModelSerializer):
    """Serializer used for listing class-section combinations."""


    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )
    class_name = serializers.CharField(
        source="school_class.name",
        read_only=True,
    )
    section_name = serializers.CharField(
        source="section.name",
        read_only=True,
    )

    class Meta:
        model = ClassSection
        fields = [
            "id",
            "academic_year",
            "academic_year_name",
            "school_class",
            "class_name",
            "section",
            "section_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "academic_year_name",
            "class_name",
            "section_name",
            "created_at",
            "updated_at",
        ]


class ClassSectionDetailSerializer(serializers.ModelSerializer):
    """Serializer used for retrieving a class-section combination."""


    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )
    class_name = serializers.CharField(
        source="school_class.name",
        read_only=True,
    )
    section_name = serializers.CharField(
        source="section.name",
        read_only=True,
    )

    class Meta:
        model = ClassSection
        fields = [
            "id",
            "academic_year",
            "academic_year_name",
            "school_class",
            "class_name",
            "section",
            "section_name",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "academic_year_name",
            "class_name",
            "section_name",
            "created_at",
            "updated_at",
        ]


class ClassSectionCreateSerializer(serializers.ModelSerializer):
    """Serializer used to create a class-section combination."""


    class Meta:
        model = ClassSection
        fields = [
            "academic_year",
            "school_class",
            "section",
        ]


class ClassSectionUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer used to update a class-section combination.

    The academic year, class, and section can be changed only when the
    resulting combination remains valid.
    """

    class Meta:
        model = ClassSection
        fields = [
            "academic_year",
            "school_class",
            "section",
        ]


class HolidayListSerializer(serializers.ModelSerializer):
    """Serializer used for listing holidays."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    class Meta:
        model = Holiday
        fields = [
            "id",
            "school",
            "school_name",
            "academic_year",
            "academic_year_name",
            "title",
            "date",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "academic_year_name",
            "created_at",
            "updated_at",
        ]


class HolidayDetailSerializer(serializers.ModelSerializer):
    """Serializer used for retrieving a holiday."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )

    class Meta:
        model = Holiday
        fields = [
            "id",
            "school",
            "school_name",
            "academic_year",
            "academic_year_name",
            "title",
            "date",
            "description",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "academic_year_name",
            "created_at",
            "updated_at",
        ]


class HolidayCreateSerializer(serializers.ModelSerializer):
    """Serializer used to create a holiday."""


    class Meta:
        model = Holiday
        fields = [
            "academic_year",
            "title",
            "date",
            "description",
        ]


class HolidayUpdateSerializer(serializers.ModelSerializer):
    """Serializer used to update a holiday."""


    class Meta:
        model = Holiday
        fields = [
            "academic_year",
            "title",
            "date",
            "description",
        ]


class WorkingDayListSerializer(serializers.ModelSerializer):
    """Serializer used for listing working-day records."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )
    day_type_display = serializers.CharField(
        source="get_day_type_display",
        read_only=True,
    )

    class Meta:
        model = WorkingDay
        fields = [
            "id",
            "school",
            "school_name",
            "academic_year",
            "academic_year_name",
            "date",
            "day_type",
            "day_type_display",
            "remarks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "academic_year_name",
            "day_type_display",
            "created_at",
            "updated_at",
        ]


class WorkingDayDetailSerializer(serializers.ModelSerializer):
    """Serializer used for retrieving a working-day record."""


    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    academic_year_name = serializers.CharField(
        source="academic_year.name",
        read_only=True,
    )
    day_type_display = serializers.CharField(
        source="get_day_type_display",
        read_only=True,
    )

    class Meta:
        model = WorkingDay
        fields = [
            "id",
            "school",
            "school_name",
            "academic_year",
            "academic_year_name",
            "date",
            "day_type",
            "day_type_display",
            "remarks",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "school",
            "school_name",
            "academic_year_name",
            "day_type_display",
            "created_at",
            "updated_at",
        ]


class WorkingDayCreateSerializer(serializers.ModelSerializer):
    """Serializer used to create a working-day record."""

    class Meta:
        model = WorkingDay
        fields = [
            "academic_year",
            "date",
            "day_type",
            "remarks",
        ]


class WorkingDayUpdateSerializer(serializers.ModelSerializer):
    """Serializer used to update a working-day record."""


    class Meta:
        model = WorkingDay
        fields = [
            "academic_year",
            "date",
            "day_type",
            "remarks",
        ]


class MarkWeekendsSerializer(serializers.Serializer):
    """
    Input for bulk-marking weekdays as weekends.

    Defaults to every Sunday in the academic year.
    """

    academic_year = serializers.PrimaryKeyRelatedField(
        queryset=AcademicYear.objects.all(),
    )
    weekdays = serializers.ListField(
        child=serializers.ChoiceField(
            choices=Weekday.choices,
        ),
        required=False,
        allow_empty=False,
        help_text=(
            "Weekdays to mark, Monday is 0 and Sunday is 6. "
            "Defaults to Sunday."
        ),
    )
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    overwrite = serializers.BooleanField(
        required=False,
        default=False,
        help_text=(
            "Replace existing working-day records for the matched "
            "dates. Off by default so deliberate entries survive."
        ),
    )

    def validate_weekdays(self, value):
        return sorted(set(value))

    def validate(self, attrs):
        attrs = super().validate(attrs)

        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if (
            start_date
            and end_date
            and end_date < start_date
        ):
            raise serializers.ValidationError(
                {
                    "end_date": (
                        "End date cannot be earlier than start date."
                    )
                }
            )

        return attrs
