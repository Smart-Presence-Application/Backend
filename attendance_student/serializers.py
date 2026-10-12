"""Serializers for face registration and student attendance APIs."""

from decouple import config
from django.utils import timezone
from rest_framework import serializers

from academics.models import ClassSection
from common.choices import AttendanceStatus, UserRole
from common.validators import validate_image_file
from schools.models import School
from students.models import Student
from students.serializers import (
    ClassSectionSummarySerializer,
    StudentScopedFieldsMixin,
)

from .models import AIJob, AttendanceRecord, AttendanceSession, FaceRegistration

MAX_ATTENDANCE_IMAGES = config("MAX_ATTENDANCE_IMAGES", default=5, cast=int)
MAX_FACE_REGISTER_IMAGES = config("MAX_FACE_REGISTER_IMAGES", default=100, cast=int)


def _role(serializer) -> str | None:
    request = serializer.context.get("request")

    if request is None or not request.user.is_authenticated:
        return None

    return request.user.role


class ClassSectionRequiredForSchoolAdminMixin:
    """
    A School Admin must say which class-section they mean.
    """

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if (
            _role(self) == UserRole.SCHOOL_ADMIN
            and attrs.get("class_section") is None
        ):
            raise serializers.ValidationError(
                {"class_section": "This field is required when acting as a School Admin."}
            )

        return attrs


class SchoolScopedFieldsMixin:
    """
    Role-shaped scope where the class-section is optional.

    Super Admins name a school (and optionally a class-section);
    School Admins may name a class-section in their school; teachers
    name neither.
    """

    def get_fields(self):
        fields = super().get_fields()
        role = _role(self)

        if role == UserRole.TEACHER:
            fields.pop("school", None)
            fields.pop("class_section", None)
        elif role == UserRole.SCHOOL_ADMIN:
            fields.pop("school", None)

        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if _role(self) == UserRole.SUPER_ADMIN and attrs.get("school") is None:
            raise serializers.ValidationError(
                {"school": "This field is required when acting as a Super Admin."}
            )

        return attrs


class FaceRegisterSerializer(SchoolScopedFieldsMixin, serializers.Serializer):
    """
    Upload one or more images and register them as faces.

    Each file is matched to a student by its name without the extension
    (``STU001.jpg`` -> student ID ``STU001``). For a single image,
    ``student`` may name the student directly instead, in which case
    the file name does not matter.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )
    student = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(),
        required=False,
    )
    images = serializers.ListField(
        child=serializers.ImageField(validators=[validate_image_file]),
        allow_empty=False,
        max_length=MAX_FACE_REGISTER_IMAGES,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)

        if attrs.get("student") is not None and len(attrs["images"]) != 1:
            raise serializers.ValidationError(
                {"images": "Exactly one image is allowed when a student is given."}
            )

        return attrs


class FaceRegisterFromProfileSerializer(
    SchoolScopedFieldsMixin,
    serializers.Serializer,
):
    """
    Register faces from profile images that are already stored.

    ``students`` picks specific students; otherwise every student in
    scope (narrowed by ``class_section`` for admins) who has a profile
    image is used. ``only_unregistered`` skips students who already
    have a face on record.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )
    students = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(),
        many=True,
        required=False,
    )
    only_unregistered = serializers.BooleanField(default=True)


class FaceScopeSerializer(SchoolScopedFieldsMixin, serializers.Serializer):
    """
    Query parameters for the face status listing.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )
    registered = serializers.BooleanField(required=False, allow_null=True, default=None)


class FaceStatusSerializer(serializers.ModelSerializer):
    face_registered = serializers.SerializerMethodField()
    face_source = serializers.SerializerMethodField()
    face_registered_at = serializers.SerializerMethodField()
    has_profile_image = serializers.BooleanField(read_only=True)

    class Meta:
        model = Student
        fields = [
            "id",
            "student_id",
            "name",
            "roll_number",
            "class_section",
            "profile_image",
            "has_profile_image",
            "face_registered",
            "face_source",
            "face_registered_at",
        ]
        read_only_fields = fields

    def _registration(self, obj) -> FaceRegistration | None:
        try:
            return obj.face_registration
        except FaceRegistration.DoesNotExist:
            return None

    def get_face_registered(self, obj) -> bool:
        return self._registration(obj) is not None

    def get_face_source(self, obj):
        registration = self._registration(obj)
        return registration.source if registration else None

    def get_face_registered_at(self, obj):
        registration = self._registration(obj)
        return registration.updated_at if registration else None


class VerifyAttendanceSerializer(
    ClassSectionRequiredForSchoolAdminMixin,
    StudentScopedFieldsMixin,
    serializers.Serializer,
):
    """
    Classroom photos to verify against a class-section's students.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )
    date = serializers.DateField(required=False)
    images = serializers.ListField(
        child=serializers.ImageField(validators=[validate_image_file]),
        allow_empty=False,
        max_length=MAX_ATTENDANCE_IMAGES,
    )

    def validate(self, attrs):
        attrs = super().validate(attrs)
        attrs.setdefault("date", timezone.localdate())
        return attrs


class RecordInputSerializer(serializers.Serializer):
    student = serializers.PrimaryKeyRelatedField(
        queryset=Student.objects.all(),
    )
    status = serializers.ChoiceField(choices=AttendanceStatus.choices)
    remarks = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
    )


def _validate_unique_students(records):
    seen = set()

    for item in records:
        if item["student"].pk in seen:
            raise serializers.ValidationError(
                f"Student {item['student'].pk} is listed more than once."
            )

        seen.add(item["student"].pk)

    return records


class ManualSessionCreateSerializer(
    ClassSectionRequiredForSchoolAdminMixin,
    StudentScopedFieldsMixin,
    serializers.Serializer,
):
    """
    Start attendance by hand, without photos.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )
    class_section = serializers.PrimaryKeyRelatedField(
        queryset=ClassSection.objects.all(),
        required=False,
    )
    date = serializers.DateField(required=False)
    records = RecordInputSerializer(many=True, required=False)

    def validate_records(self, value):
        return _validate_unique_students(value)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        attrs.setdefault("date", timezone.localdate())
        return attrs


class RecordsUpdateSerializer(serializers.Serializer):
    records = RecordInputSerializer(many=True, allow_empty=False)

    def validate_records(self, value):
        return _validate_unique_students(value)


class AttendanceRecordSerializer(serializers.ModelSerializer):
    student_id = serializers.CharField(source="student.student_id", read_only=True)
    student_name = serializers.CharField(source="student.name", read_only=True)
    roll_number = serializers.CharField(source="student.roll_number", read_only=True)
    updated_by_name = serializers.CharField(source="updated_by.name", read_only=True, default=None)

    class Meta:
        model = AttendanceRecord
        fields = [
            "id",
            "student",
            "student_id",
            "student_name",
            "roll_number",
            "status",
            "source",
            "ai_status",
            "similarity",
            "face_registered",
            "remarks",
            "updated_by",
            "updated_by_name",
            "updated_at",
        ]
        read_only_fields = fields


class AttendanceSessionListSerializer(serializers.ModelSerializer):
    school_name = serializers.CharField(source="school.name", read_only=True)
    class_section_detail = ClassSectionSummarySerializer(source="class_section", read_only=True)
    created_by_name = serializers.CharField(source="created_by.name", read_only=True, default=None)
    locked_by_name = serializers.CharField(source="locked_by.name", read_only=True, default=None)
    total_students = serializers.IntegerField(read_only=True, default=None)
    present_count = serializers.IntegerField(read_only=True, default=None)
    absent_count = serializers.IntegerField(read_only=True, default=None)

    class Meta:
        model = AttendanceSession
        fields = [
            "id",
            "school",
            "school_name",
            "class_section",
            "class_section_detail",
            "date",
            "status",
            "image_count",
            "detected_faces",
            "verified_at",
            "total_students",
            "present_count",
            "absent_count",
            "created_by",
            "created_by_name",
            "locked_by",
            "locked_by_name",
            "locked_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class AttendanceSessionDetailSerializer(AttendanceSessionListSerializer):
    records = AttendanceRecordSerializer(many=True, read_only=True)
    not_registered_count = serializers.SerializerMethodField()

    class Meta(AttendanceSessionListSerializer.Meta):
        fields = AttendanceSessionListSerializer.Meta.fields + [
            "not_registered_count",
            "records",
        ]
        read_only_fields = fields

    def to_representation(self, instance):
        """Count from the prefetched records so the query count stays fixed."""

        records = list(instance.records.all())
        instance.total_students = len(records)
        instance.present_count = sum(r.status == AttendanceStatus.PRESENT for r in records)
        instance.absent_count = instance.total_students - instance.present_count
        return super().to_representation(instance)

    def get_not_registered_count(self, obj) -> int:
        return sum(not r.face_registered for r in obj.records.all())


class AIJobSerializer(serializers.ModelSerializer):
    """
    A background AI job as the client polls it.

    ``done`` turns true once the job succeeded or failed; until then
    poll again after ``poll_after`` seconds. ``result`` is set on
    success; ``error`` / ``error_status`` / ``errors`` on failure, the
    same message, HTTP status and errors the endpoint would have
    answered had it done the work inside the request.
    """

    done = serializers.SerializerMethodField()
    percent = serializers.SerializerMethodField()
    poll_after = serializers.SerializerMethodField()

    class Meta:
        model = AIJob
        fields = [
            "id",
            "kind",
            "status",
            "done",
            "message",
            "total",
            "processed",
            "succeeded",
            "failed",
            "percent",
            "result",
            "error",
            "error_status",
            "errors",
            "poll_after",
            "created_at",
            "started_at",
            "finished_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_done(self, obj) -> bool:
        return not obj.is_active

    def get_percent(self, obj) -> int | None:
        if not obj.is_active:
            return 100

        if not obj.total:
            return None

        return min(99, round(obj.processed * 100 / obj.total))

    def get_poll_after(self, obj) -> int | None:
        return None if not obj.is_active else 2
