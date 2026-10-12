"""Serializers for teacher APIs."""

from rest_framework import serializers

from academics.models import ClassSection
from common.choices import Gender, UserRole
from common.validators import validate_csv_file, validate_phone
from schools.models import School

from .models import Teacher


class ClassSectionSummarySerializer(serializers.ModelSerializer):
    """Compact class-section representation for nesting."""

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
        ]
        read_only_fields = fields


class TeacherListSerializer(serializers.ModelSerializer):
    """Serializer used for listing teachers."""

    name = serializers.CharField(
        source="user.name",
        read_only=True,
    )
    email = serializers.EmailField(
        source="user.email",
        read_only=True,
    )
    phone_number = serializers.CharField(
        source="user.phone_number",
        read_only=True,
    )
    gender = serializers.CharField(
        source="user.gender",
        read_only=True,
    )
    is_active = serializers.BooleanField(
        source="user.is_active",
        read_only=True,
    )
    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    class_section_detail = ClassSectionSummarySerializer(
        source="class_section",
        read_only=True,
    )

    class Meta:
        model = Teacher
        fields = [
            "id",
            "employee_id",
            "name",
            "email",
            "phone_number",
            "gender",
            "is_active",
            "school",
            "school_name",
            "class_section",
            "class_section_detail",
            "joining_date",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TeacherDetailSerializer(TeacherListSerializer):
    """
    Serializer used for retrieving a single teacher.

    Adds the address block that the list view leaves out.
    """

    profile_image = serializers.ImageField(
        source="user.profile_image",
        read_only=True,
    )

    class Meta(TeacherListSerializer.Meta):
        fields = TeacherListSerializer.Meta.fields + [
            "profile_image",
            "address",
            "city",
            "state",
            "country",
            "pincode",
        ]
        read_only_fields = fields


class TeacherProfileSerializer(serializers.ModelSerializer):
    """What a teacher sees when looking at their own record."""

    name = serializers.CharField(
        source="user.name",
        read_only=True,
    )
    email = serializers.EmailField(
        source="user.email",
        read_only=True,
    )
    phone_number = serializers.CharField(
        source="user.phone_number",
        read_only=True,
    )
    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    class_section_detail = ClassSectionSummarySerializer(
        source="class_section",
        read_only=True,
    )

    class Meta:
        model = Teacher
        fields = [
            "id",
            "employee_id",
            "name",
            "email",
            "phone_number",
            "school",
            "school_name",
            "class_section",
            "class_section_detail",
            "address",
            "city",
            "state",
            "country",
            "pincode",
            "joining_date",
        ]
        read_only_fields = fields


class TeacherWritableFieldsMixin:
    """
    The teacher fields an administrator may set.

    ``name``, ``email``, ``phone_number`` and ``gender`` live on the
    user record; the service layer splits them back out.
    """

    def validate_employee_id(self, value):
        return value.strip().upper()

    def validate_email(self, value):
        return value.strip().lower()

    def validate_name(self, value):
        return value.strip()


class TeacherCreateSerializer(
    TeacherWritableFieldsMixin,
    serializers.Serializer,
):
    """
    Serializer used to create a teacher.

    Super Admins must name the school. For School Admins the field is
    removed and the view supplies their own school.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )

    employee_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone_number = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        validators=[validate_phone],
    )
    gender = serializers.ChoiceField(
        choices=Gender.choices,
        required=False,
        default=Gender.OTHER,
    )

    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
        allow_null=True,
    )

    address = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    city = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    state = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    country = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    pincode = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
    )
    joining_date = serializers.DateField(
        required=False,
        allow_null=True,
    )

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


class TeacherCSVRowSerializer(
    TeacherWritableFieldsMixin,
    serializers.Serializer,
):
    """
    Validates one row of a bulk-upload CSV.

    The school comes from the request, not the file, so a CSV cannot
    move teachers into a school the uploader does not administer.
    """

    employee_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    phone_number = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        validators=[validate_phone],
    )
    gender = serializers.ChoiceField(
        choices=Gender.choices,
        required=False,
        default=Gender.OTHER,
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )
    city = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    state = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    country = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )
    pincode = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
        default="",
    )
    joining_date = serializers.DateField(required=False)

    def validate_gender(self, value):
        return value.strip().upper()


class TeacherUpdateSerializer(
    TeacherWritableFieldsMixin,
    serializers.Serializer,
):
    """
    Serializer used to update a teacher.

    The school is deliberately absent: moving a teacher between schools
    would orphan their class-section assignment.
    """

    employee_id = serializers.CharField(
        max_length=50,
        required=False,
    )
    name = serializers.CharField(
        max_length=150,
        required=False,
    )
    email = serializers.EmailField(required=False)
    phone_number = serializers.CharField(
        max_length=10,
        required=False,
        allow_blank=True,
        validators=[validate_phone],
    )
    gender = serializers.ChoiceField(
        choices=Gender.choices,
        required=False,
    )
    address = serializers.CharField(
        required=False,
        allow_blank=True,
    )
    city = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    state = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    country = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
    )
    pincode = serializers.CharField(
        max_length=20,
        required=False,
        allow_blank=True,
    )
    joining_date = serializers.DateField(
        required=False,
        allow_null=True,
    )


class TeacherBulkUploadSerializer(serializers.Serializer):
    """Serializer used for CSV bulk upload."""

    file = serializers.FileField(
        validators=[validate_csv_file],
    )
    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )

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
                        "This field is required when uploading "
                        "as a Super Admin."
                    )
                }
            )

        return attrs


class TeacherStatusSerializer(serializers.Serializer):
    """Activate or deactivate a teacher's login."""

    is_active = serializers.BooleanField()


class ClassSectionAssignmentSerializer(serializers.Serializer):
    """Assign or transfer a teacher to a class-section."""

    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
    )
