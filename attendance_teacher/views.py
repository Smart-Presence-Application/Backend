"""Teacher check-in / check-out attendance API views."""

from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from common.pagination import StandardResultsPagination
from common.permissions import (
    IsAttendanceManager,
    IsSuperOrSchoolAdmin,
    IsTeacher,
)
from common.responses import (
    created_response,
    deleted_response,
    success_response,
    updated_response,
)
from students.selectors import is_school_admin, is_super_admin, is_teacher
from teachers.selectors import get_teacher_profile

from . import services
from .attendance_filters import TeacherAttendanceFilter
from .selectors import get_attendance_visible_to
from .serializers import (
    CaptureSerializer,
    SchoolParamSerializer,
    SettingsSerializer,
    SettingsUpdateSerializer,
    SummaryParamSerializer,
    TeacherAttendanceSerializer,
    VerifySerializer,
)


def to_drf_error(exc: DjangoValidationError) -> ValidationError:
    if hasattr(exc, "error_dict"):
        return ValidationError(exc.message_dict)

    return ValidationError({"detail": exc.messages})


class TeacherAttendanceBaseMixin:
    permission_classes = [
        IsAuthenticated,
        IsAttendanceManager,
    ]

    def get_own_teacher(self):
        teacher = get_teacher_profile(self.request.user)

        if teacher is None:
            raise ValidationError({"detail": "No teacher profile is linked to your account."})

        return teacher

    def resolve_school(self, validated_data):
        """
        The school the caller means: named by a Super Admin, implied
        for everyone else.
        """

        user = self.request.user

        if is_super_admin(user):
            return validated_data["school"]

        if is_school_admin(user):
            school = getattr(user, "managed_school", None)
        elif is_teacher(user):
            school = getattr(self.get_own_teacher(), "school", None)
        else:
            school = None

        if school is None:
            raise ValidationError({"detail": "You are not linked to a school."})

        return school

    def get_attendance_or_404(self, pk):
        attendance = get_attendance_visible_to(self.request.user).filter(pk=pk).first()

        if attendance is None:
            raise NotFound("Attendance not found.")

        return attendance


class CaptureAPIView(TeacherAttendanceBaseMixin, generics.GenericAPIView):
    permission_classes = [IsAuthenticated, IsTeacher]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = CaptureSerializer
    capture = None
    message = ""

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            attendance = self.capture(
                teacher=self.get_own_teacher(),
                image=serializer.validated_data["image"],
                captured_at=serializer.validated_data["captured_at"],
                offline=serializer.validated_data["offline"],
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return created_response(
            self.message,
            TeacherAttendanceSerializer(attendance).data,
        )


class CheckInAPIView(CaptureAPIView):
    """
    Teacher checks in (school entry) with a live camera photo.
    """

    capture = staticmethod(services.check_in)
    message = "Checked in successfully. Awaiting school admin verification."


class CheckOutAPIView(CaptureAPIView):
    """
    Teacher checks out (school exit) with a live camera photo.
    """

    capture = staticmethod(services.check_out)
    message = "Checked out successfully. Awaiting school admin verification."


class TodayAPIView(TeacherAttendanceBaseMixin, generics.GenericAPIView):
    """
    The teacher's own record for today, or null if not checked in.
    """

    permission_classes = [IsAuthenticated, IsTeacher]

    def get(self, request, *args, **kwargs):
        attendance = (
            get_attendance_visible_to(request.user)
            .filter(date=timezone.localdate())
            .first()
        )

        return success_response(
            "Today's attendance fetched successfully.",
            TeacherAttendanceSerializer(attendance).data if attendance else None,
        )


class TeacherAttendanceListAPIView(
    TeacherAttendanceBaseMixin,
    generics.ListAPIView,
):
    """
    Drafts and verified days. Teachers see their own; School Admins
    their school's.
    """

    serializer_class = TeacherAttendanceSerializer
    pagination_class = StandardResultsPagination
    filter_backends = [
        DjangoFilterBackend,
        filters.SearchFilter,
        filters.OrderingFilter,
    ]
    filterset_class = TeacherAttendanceFilter
    search_fields = ["teacher__employee_id", "teacher__user__name"]
    ordering_fields = ["date", "check_in_captured_at", "status"]
    ordering = ["-date", "teacher__employee_id"]

    def get_queryset(self):
        return get_attendance_visible_to(self.request.user)

    def list(self, request, *args, **kwargs):
        queryset = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(queryset)

        if page is not None:
            return self.get_paginated_response(self.get_serializer(page, many=True).data)

        return success_response(
            "Teacher attendance fetched successfully.",
            self.get_serializer(queryset, many=True).data,
        )


class TeacherAttendanceDetailAPIView(
    TeacherAttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    Read a teacher's day, or delete it with its photos.

    Only admins may delete, whether the day is verified or not.
    """

    def get_permissions(self):
        if self.request.method == "DELETE":
            return [IsAuthenticated(), IsSuperOrSchoolAdmin()]

        return super().get_permissions()

    def get(self, request, pk, *args, **kwargs):
        return success_response(
            "Teacher attendance fetched successfully.",
            TeacherAttendanceSerializer(self.get_attendance_or_404(pk)).data,
        )

    def delete(self, request, pk, *args, **kwargs):
        attendance = self.get_attendance_or_404(pk)
        data = {
            "id": attendance.pk,
            "teacher": attendance.teacher_id,
            "date": attendance.date,
        }

        services.delete_attendance(attendance=attendance, actor=request.user)

        return deleted_response("Teacher attendance deleted successfully.", data)


class TeacherAttendanceVerifyAPIView(
    TeacherAttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    School Admin reviews a day, optionally adjusting the times or
    marking it a half / full day, and finalises it.
    """

    permission_classes = [IsAuthenticated, IsSuperOrSchoolAdmin]
    serializer_class = VerifySerializer

    def post(self, request, pk, *args, **kwargs):
        attendance = self.get_attendance_or_404(pk)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            attendance = services.verify_attendance(
                attendance=attendance,
                actor=request.user,
                **serializer.validated_data,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return updated_response(
            "Teacher attendance verified successfully.",
            TeacherAttendanceSerializer(self.get_attendance_or_404(attendance.pk)).data,
        )


class TeacherAttendanceSettingsAPIView(
    TeacherAttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    How many hours make a full day and a half day.

    Everyone may read their school's settings; only admins may change
    them. Super Admins pass ``school``.
    """

    parser_classes = [JSONParser, FormParser, MultiPartParser]

    def get_permissions(self):
        if self.request.method in ("PATCH", "PUT"):
            return [IsAuthenticated(), IsSuperOrSchoolAdmin()]

        return super().get_permissions()

    def get(self, request, *args, **kwargs):
        params = SchoolParamSerializer(
            data=request.query_params,
            context={"request": request},
        )
        params.is_valid(raise_exception=True)

        school = self.resolve_school(params.validated_data)

        return success_response(
            "Teacher attendance settings fetched successfully.",
            SettingsSerializer(services.get_attendance_settings(school)).data,
        )

    def patch(self, request, *args, **kwargs):
        serializer = SettingsUpdateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        data = dict(serializer.validated_data)
        school = self.resolve_school(data)
        data.pop("school", None)

        try:
            current = services.update_attendance_settings(
                school=school,
                actor=request.user,
                validated_data=data,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc)

        return updated_response(
            "Teacher attendance settings updated successfully.",
            SettingsSerializer(current).data,
        )

    def put(self, request, *args, **kwargs):
        return self.patch(request, *args, **kwargs)


class TeacherAttendanceSummaryAPIView(
    TeacherAttendanceBaseMixin,
    generics.GenericAPIView,
):
    """
    Totals per teacher over a date range: working hours, full days,
    half days, and working days (two half days = one day).

    Teachers get their own row; admins get one row per teacher, or one
    teacher with ``teacher``.
    """

    def get(self, request, *args, **kwargs):
        params = SummaryParamSerializer(
            data=request.query_params,
            context={"request": request},
        )
        params.is_valid(raise_exception=True)
        data = params.validated_data

        queryset = get_attendance_visible_to(request.user)

        if not is_teacher(request.user):
            queryset = queryset.filter(school=self.resolve_school(data))

        if data.get("teacher") is not None:
            queryset = queryset.filter(teacher=data["teacher"])

        if data.get("date_from"):
            queryset = queryset.filter(date__gte=data["date_from"])

        if data.get("date_to"):
            queryset = queryset.filter(date__lte=data["date_to"])

        return success_response(
            "Teacher attendance summary fetched successfully.",
            {
                "date_from": data.get("date_from"),
                "date_to": data.get("date_to"),
                "teachers": services.summarise(queryset),
            },
        )
