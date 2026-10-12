from django.urls import path

from .views import (
    CheckInAPIView,
    CheckOutAPIView,
    TeacherAttendanceDetailAPIView,
    TeacherAttendanceListAPIView,
    TeacherAttendanceSettingsAPIView,
    TeacherAttendanceSummaryAPIView,
    TeacherAttendanceVerifyAPIView,
    TodayAPIView,
)

app_name = "attendance_teacher"

urlpatterns = [
    path(
        "check-in/",
        CheckInAPIView.as_view(),
        name="check-in",
    ),
    path(
        "check-out/",
        CheckOutAPIView.as_view(),
        name="check-out",
    ),
    path(
        "today/",
        TodayAPIView.as_view(),
        name="today",
    ),
    path(
        "records/",
        TeacherAttendanceListAPIView.as_view(),
        name="record-list",
    ),
    path(
        "records/<int:pk>/",
        TeacherAttendanceDetailAPIView.as_view(),
        name="record-detail",
    ),
    path(
        "records/<int:pk>/verify/",
        TeacherAttendanceVerifyAPIView.as_view(),
        name="record-verify",
    ),
    path(
        "settings/",
        TeacherAttendanceSettingsAPIView.as_view(),
        name="settings",
    ),
    path(
        "summary/",
        TeacherAttendanceSummaryAPIView.as_view(),
        name="summary",
    ),
]
