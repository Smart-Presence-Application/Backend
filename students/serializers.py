"""Serializers for student APIs."""

from django.core.exceptions import ObjectDoesNotExist
from rest_framework import serializers

from academics.models import ClassSection
from common.choices import UserRole
from common.validators import validate_csv_file, validate_image_file
from schools.models import School

from .models import Student
from .services import ROLL_CHOICES, ROLL_KEEP


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


class StudentListSerializer(serializers.ModelSerializer):
    """Serializer used for listing students."""

    school_name = serializers.CharField(
        source="school.name",
        read_only=True,
    )
    class_section_detail = ClassSectionSummarySerializer(
        source="class_section",
        read_only=True,
    )
    has_profile_image = serializers.BooleanField(read_only=True)
    face_registered = serializers.SerializerMethodField()

    class Meta:
        model = Student
        fields = [
            "id",
            "student_id",
            "name",
            "roll_number",
            "school",
            "school_name",
            "class_section",
            "class_section_detail",
            "profile_image",
            "has_profile_image",
            "face_registered",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_face_registered(self, obj) -> bool:
        """Whether the AI can recognise this student in classroom photos."""

        try:
            return obj.face_registration is not None
        except ObjectDoesNotExist:
            return False


class StudentDetailSerializer(StudentListSerializer):
    """Serializer used for retrieving a single student."""


class StudentScopedFieldsMixin:
    """
    Shapes the school and class-section fields to the caller's role.

    Super Admins name both the school and the class-section; School
    Admins name only the class-section; teachers name neither, because
    the class-section they are assigned to is the only one they may
    use.
    """

    def get_fields(self):
        fields = super().get_fields()

        request = self.context.get("request")

        if request is None or not request.user.is_authenticated:
            return fields

        role = request.user.role

        if role == UserRole.TEACHER:
            fields.pop("school", None)
            fields.pop("class_section", None)
        elif role == UserRole.SCHOOL_ADMIN:
            fields.pop("school", None)

        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)

        request = self.context.get("request")

        if request is None:
            return attrs

        role = request.user.role

        if role != UserRole.SUPER_ADMIN:
            return attrs

        missing = {}

        if attrs.get("school") is None:
            missing["school"] = (
                "This field is required when acting as a Super Admin."
            )

        if attrs.get("class_section") is None:
            missing["class_section"] = (
                "This field is required when acting as a Super Admin."
            )

        if missing:
            raise serializers.ValidationError(missing)

        return attrs


class StudentCreateSerializer(
    StudentScopedFieldsMixin,
    serializers.Serializer,
):
    """Serializer used to enrol a student."""

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )

    name = serializers.CharField(max_length=255)
    student_id = serializers.CharField(max_length=50)
    roll_number = serializers.CharField(max_length=20)
    profile_image = serializers.ImageField(
        required=False,
        allow_null=True,
        validators=[validate_image_file],
    )

    def validate_name(self, value):
        return value.strip()

    def validate_student_id(self, value):
        return value.strip().upper()

    def validate_roll_number(self, value):
        return value.strip()

    def validate(self, attrs):
        """A School Admin must name the class-section, since their school usually has many."""
        attrs = super().validate(attrs)

        request = self.context.get("request")

        if (
            request is not None
            and request.user.role == UserRole.SCHOOL_ADMIN
            and attrs.get("class_section") is None
        ):
            raise serializers.ValidationError(
                {
                    "class_section": (
                        "This field is required when acting as a "
                        "School Admin."
                    )
                }
            )

        return attrs


class StudentUpdateSerializer(
    StudentScopedFieldsMixin,
    serializers.Serializer,
):
    """
    Serializer used to update a student.

    Every field is optional; ``class_section`` moves the student, and
    the view checks that the destination is one the caller may use.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )

    name = serializers.CharField(
        max_length=255,
        required=False,
    )
    student_id = serializers.CharField(
        max_length=50,
        required=False,
    )
    roll_number = serializers.CharField(
        max_length=20,
        required=False,
    )

    def validate_name(self, value):
        return value.strip()

    def validate_student_id(self, value):
        return value.strip().upper()

    def validate_roll_number(self, value):
        return value.strip()

    def validate(self, attrs):
        """
        Skip the Super Admin requirement that both fields be present.

        On an update the student already has a school and a section, so
        naming neither simply means "leave them alone".
        """

        if not attrs:
            raise serializers.ValidationError(
                "No fields were supplied to update.",
            )

        return attrs


class StudentProfileImageSerializer(serializers.Serializer):
    """Upload or replace a student's profile image."""

    profile_image = serializers.ImageField(
        validators=[validate_image_file],
    )


class StudentCSVRowSerializer(serializers.Serializer):
    """
    Validates one row of a bulk-upload CSV.

    The class-section is not a column: it comes from the request, so a
    file cannot place students outside the uploader's scope.
    """

    student_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=255)
    roll_number = serializers.CharField(max_length=20)

    def validate_student_id(self, value):
        return value.strip().upper()

    def validate_name(self, value):
        return value.strip()

    def validate_roll_number(self, value):
        return value.strip()


class StudentBulkUploadSerializer(
    StudentScopedFieldsMixin,
    serializers.Serializer,
):
    """
    Serializer used for CSV bulk upload.

    Carries the same role-shaped school and class-section fields as a
    single enrolment, so the rules do not differ between the two ways
    of adding students.
    """

    file = serializers.FileField(
        validators=[validate_csv_file],
    )
    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)

        request = self.context.get("request")

        if (
            request is not None
            and request.user.role == UserRole.SCHOOL_ADMIN
            and attrs.get("class_section") is None
        ):
            raise serializers.ValidationError(
                {
                    "class_section": (
                        "This field is required when acting as a "
                        "School Admin."
                    )
                }
            )

        return attrs


class StudentPromoteSerializer(serializers.Serializer):
    """Move the given students into another class-section."""

    student_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        min_length=1,
        max_length=1000,
    )
    to_class_section = serializers.IntegerField(min_value=1)
    roll_numbers = serializers.ChoiceField(choices=ROLL_CHOICES, default=ROLL_KEEP)
