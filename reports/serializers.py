from rest_framework import serializers

from attendance_student.models import SessionStatus
from attendance_teacher.models import TeacherAttendanceStatus, WorkDayType
from common.choices import AttendanceStatus, Status, UserRole


class ReportFilterSerializer(serializers.Serializer):
    """
    Query-string filters for report downloads. All optional; each
    report applies the ones it understands and ignores the rest.
    """

    school = serializers.IntegerField(required=False, min_value=1)
    academic_year = serializers.IntegerField(required=False, min_value=1)
    class_section = serializers.IntegerField(required=False, min_value=1)
    school_class = serializers.IntegerField(required=False, min_value=1)
    section = serializers.IntegerField(required=False, min_value=1)
    student = serializers.IntegerField(required=False, min_value=1)
    teacher = serializers.IntegerField(required=False, min_value=1)

    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)

    status = serializers.ChoiceField(choices=AttendanceStatus.choices, required=False)
    session_status = serializers.ChoiceField(choices=SessionStatus.choices, required=False)
    verification = serializers.ChoiceField(choices=TeacherAttendanceStatus.choices, required=False)
    day_type = serializers.ChoiceField(choices=WorkDayType.choices, required=False)
    school_status = serializers.ChoiceField(choices=Status.choices, required=False)
    role = serializers.ChoiceField(choices=UserRole.choices, required=False)
    is_active = serializers.BooleanField(required=False, allow_null=True, default=None)

    def validate(self, attrs):
        start, end = attrs.get("date_from"), attrs.get("date_to")

        if start and end and start > end:
            raise serializers.ValidationError({"date_to": "Must be on or after the start date."})

        return {key: value for key, value in attrs.items() if value is not None}
