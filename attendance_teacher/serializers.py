"""Serializers for teacher attendance APIs."""

from rest_framework import serializers

from common.choices import UserRole
from common.validators import validate_image_file
from schools.models import School
from teachers.models import Teacher

from .models import (
    TeacherAttendance,
    TeacherAttendanceSettings,
    WorkDayType,
)


def _hours(minutes):
    return None if minutes is None else round(minutes / 60, 2)


class CaptureSerializer(serializers.Serializer):
    """
    A camera photo for check-in or check-out.

    ``captured_at`` is the device time the photo was taken; it is only
    used to reject stale photos; the recorded time is the server's.
    ``offline`` is sent when the app queued the photo without internet
    and is syncing it now.
    """

    image = serializers.ImageField(validators=[validate_image_file])
    captured_at = serializers.DateTimeField()
    offline = serializers.BooleanField(default=False)


class TeacherAttendanceSerializer(serializers.ModelSerializer):
    """
    Shows captured, verified and effective times side by side, for
    drafts and verified days alike.
    """

    employee_id = serializers.CharField(source="teacher.employee_id", read_only=True)
    teacher_name = serializers.CharField(source="teacher.user.name", read_only=True)
    check_in_at = serializers.DateTimeField(read_only=True)
    check_out_at = serializers.DateTimeField(read_only=True)
    worked_minutes = serializers.SerializerMethodField()
    worked_hours = serializers.SerializerMethodField()
    verified_by_name = serializers.CharField(
        source="verified_by.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = TeacherAttendance
        fields = [
            "id",
            "teacher",
            "employee_id",
            "teacher_name",
            "school",
            "date",
            "status",
            "check_in_at",
            "check_out_at",
            "check_in_captured_at",
            "check_out_captured_at",
            "check_in_verified_at",
            "check_out_verified_at",
            "check_in_image",
            "check_out_image",
            "check_in_offline",
            "check_out_offline",
            "worked_minutes",
            "worked_hours",
            "day_type",
            "day_type_overridden",
            "remarks",
            "verified_by",
            "verified_by_name",
            "verified_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_worked_minutes(self, obj):
        """Verified days report the stored snapshot; drafts the live value."""

        if obj.is_verified:
            return obj.worked_minutes

        return obj.current_worked_minutes

    def get_worked_hours(self, obj):
        return _hours(self.get_worked_minutes(obj))


class VerifySerializer(serializers.Serializer):
    """
    Times are wall-clock times on the attendance date (``HH:MM``).
    """

    check_in_time = serializers.TimeField(required=False)
    check_out_time = serializers.TimeField(required=False)
    day_type = serializers.ChoiceField(
        choices=WorkDayType.choices,
        required=False,
        allow_null=True,
    )
    remarks = serializers.CharField(max_length=255, required=False, allow_blank=True)


class SchoolParamSerializer(serializers.Serializer):
    """
    ``school`` is needed only by Super Admins; everyone else is pinned
    to their own school.
    """

    school = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(),
        required=False,
    )

    def validate(self, attrs):
        request = self.context["request"]

        if request.user.role == UserRole.SUPER_ADMIN and attrs.get("school") is None:
            raise serializers.ValidationError(
                {"school": "This field is required when acting as a Super Admin."}
            )

        return attrs


class SettingsSerializer(serializers.ModelSerializer):
    full_day_hours = serializers.SerializerMethodField()
    half_day_hours = serializers.SerializerMethodField()

    class Meta:
        model = TeacherAttendanceSettings
        fields = [
            "school",
            "full_day_minutes",
            "full_day_hours",
            "half_day_minutes",
            "half_day_hours",
            "updated_at",
        ]
        read_only_fields = ["school", "updated_at"]

    def get_full_day_hours(self, obj):
        return _hours(obj.full_day_minutes)

    def get_half_day_hours(self, obj):
        return _hours(obj.half_day_minutes)


class SettingsUpdateSerializer(SchoolParamSerializer):
    full_day_minutes = serializers.IntegerField(min_value=1, max_value=24 * 60, required=False)
    half_day_minutes = serializers.IntegerField(min_value=1, max_value=24 * 60, required=False)


class SummaryParamSerializer(SchoolParamSerializer):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    teacher = serializers.PrimaryKeyRelatedField(
        queryset=Teacher.objects.all(),
        required=False,
    )

    def validate(self, attrs):
        """A teacher's summary is always their own, so no school is needed."""

        request = self.context["request"]

        if request.user.role != UserRole.TEACHER:
            attrs = super().validate(attrs)

        if (
            attrs.get("date_from")
            and attrs.get("date_to")
            and attrs["date_from"] > attrs["date_to"]
        ):
            raise serializers.ValidationError({"date_to": "Must be on or after date_from."})

        return attrs
