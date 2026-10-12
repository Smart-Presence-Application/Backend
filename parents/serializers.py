"""Serializers for parent APIs."""

from rest_framework import serializers

from attendance_student.models import AttendanceRecord
from common.choices import UserRole
from common.validators import validate_csv_file, validate_phone
from schools.models import School
from students.serializers import StudentListSerializer

from .models import Parent, ParentNotification


class ParentLoginSerializer(serializers.Serializer):
    phone_number = serializers.CharField(validators=[validate_phone])
    password = serializers.CharField(write_only=True, trim_whitespace=False)


class ParentSerializer(serializers.ModelSerializer):
    """
    Staff view of a parent.

    ``initial_password`` is the generated password staff can hand over;
    it is null once the parent has set their own.
    """

    user = serializers.IntegerField(source="user.id", read_only=True)
    name = serializers.CharField(source="user.name", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    students = StudentListSerializer(many=True, read_only=True)
    initial_password = serializers.SerializerMethodField()
    password_changed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Parent
        fields = [
            "id",
            "user",
            "name",
            "phone_number",
            "is_active",
            "students",
            "initial_password",
            "password_changed",
            "last_login",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_initial_password(self, obj):
        return obj.initial_password or None


class ParentCreateSerializer(serializers.Serializer):
    """
    Create a parent for a student, or link the student to the existing
    parent with this mobile number.

    The student is named by their school student ID. Teachers can name
    only students of their class-section and School Admins students of
    their school; a Super Admin also names the school.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    student_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(validators=[validate_phone])

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")

        if request is not None and request.user.role != UserRole.SUPER_ADMIN:
            fields.pop("school", None)

        return fields

    def validate_student_id(self, value):
        return value.strip().upper()

    def validate_name(self, value):
        value = " ".join(value.split())

        if not value:
            raise serializers.ValidationError("This field may not be blank.")

        return value

    def validate(self, attrs):
        request = self.context.get("request")

        if (
            request is not None
            and request.user.role == UserRole.SUPER_ADMIN
            and attrs.get("school") is None
        ):
            raise serializers.ValidationError(
                {"school": "This field is required when acting as a Super Admin."}
            )

        return attrs


class ParentUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=150, required=False)
    phone_number = serializers.CharField(validators=[validate_phone], required=False)

    def validate_name(self, value):
        value = " ".join(value.split())

        if not value:
            raise serializers.ValidationError("This field may not be blank.")

        return value

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError("No fields were supplied to update.")

        return attrs


class ParentProfileSerializer(serializers.ModelSerializer):
    """
    What a parent sees about themselves.

    ``password_changed`` is False while the parent still signs in with the
    password the school gave them.
    """

    name = serializers.CharField(source="user.name", read_only=True)
    phone_number = serializers.CharField(source="user.phone_number", read_only=True)
    students = StudentListSerializer(many=True, read_only=True)
    password_changed = serializers.BooleanField(read_only=True)

    class Meta:
        model = Parent
        fields = ["id", "name", "phone_number", "students", "password_changed"]
        read_only_fields = fields


class ChildAttendanceSerializer(serializers.ModelSerializer):
    date = serializers.DateField(source="session.date", read_only=True)
    student_id = serializers.CharField(source="student.student_id", read_only=True)
    student_name = serializers.CharField(source="student.name", read_only=True)
    class_name = serializers.CharField(
        source="session.class_section.school_class.name",
        read_only=True,
    )
    section_name = serializers.CharField(
        source="session.class_section.section.name",
        read_only=True,
    )

    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "date",
            "student",
            "student_id",
            "student_name",
            "class_name",
            "section_name",
            "status",
            "remarks",
        ]
        read_only_fields = fields


class ParentNotificationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.name", read_only=True)

    class Meta:
        model = ParentNotification
        fields = [
            "id",
            "student",
            "student_name",
            "date",
            "status",
            "title",
            "message",
            "is_read",
            "read_at",
            "created_at",
        ]
        read_only_fields = fields


class MarkReadSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        allow_empty=False,
    )


class ParentCSVRowSerializer(serializers.Serializer):
    """One row of a bulk parent upload: a child and their parent."""

    student_id = serializers.CharField(max_length=50)
    name = serializers.CharField(max_length=150)
    phone_number = serializers.CharField(validators=[validate_phone])

    def validate_student_id(self, value):
        return value.strip().upper()

    def validate_name(self, value):
        value = " ".join(value.split())

        if not value:
            raise serializers.ValidationError("This field may not be blank.")

        return value

    def validate_phone_number(self, value):
        return value.strip()


class ParentBulkUploadSerializer(serializers.Serializer):
    """
    A CSV of ``student_id, name, phone_number``. Super Admins also name
    the school the student IDs belong to; everyone else is limited to
    the students they can already see.
    """

    file = serializers.FileField(validators=[validate_csv_file])
    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get("request")

        if request is not None and request.user.role != UserRole.SUPER_ADMIN:
            fields.pop("school", None)

        return fields

    def validate(self, attrs):
        request = self.context.get("request")

        if (
            request is not None
            and request.user.role == UserRole.SUPER_ADMIN
            and attrs.get("school") is None
        ):
            raise serializers.ValidationError(
                {"school": "This field is required when acting as a Super Admin."}
            )

        return attrs
