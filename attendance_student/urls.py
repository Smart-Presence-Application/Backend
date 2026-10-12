from django.urls import path

from .views import (
    AIJobDetailAPIView,
    AttendanceLockAPIView,
    AttendanceRecordsUpdateAPIView,
    AttendanceSessionDetailAPIView,
    AttendanceSessionListCreateAPIView,
    AttendanceUnlockAPIView,
    AttendanceVerifyAPIView,
    FaceDeleteAPIView,
    FaceListAPIView,
    FaceRegisterAPIView,
    FaceRegisterFromProfileAPIView,
)

app_name = "attendance_student"

urlpatterns = [
    path(
        "faces/",
        FaceListAPIView.as_view(),
        name="face-list",
    ),
    path(
        "faces/register/",
        FaceRegisterAPIView.as_view(),
        name="face-register",
    ),
    path(
        "faces/register-from-profile/",
        FaceRegisterFromProfileAPIView.as_view(),
        name="face-register-from-profile",
    ),
    path(
        "faces/<int:student_pk>/",
        FaceDeleteAPIView.as_view(),
        name="face-delete",
    ),
    path(
        "jobs/<uuid:pk>/",
        AIJobDetailAPIView.as_view(),
        name="ai-job-detail",
    ),
    path(
        "verify/",
        AttendanceVerifyAPIView.as_view(),
        name="attendance-verify",
    ),
    path(
        "sessions/",
        AttendanceSessionListCreateAPIView.as_view(),
        name="attendance-session-list-create",
    ),
    path(
        "sessions/<int:pk>/",
        AttendanceSessionDetailAPIView.as_view(),
        name="attendance-session-detail",
    ),
    path(
        "sessions/<int:pk>/records/",
        AttendanceRecordsUpdateAPIView.as_view(),
        name="attendance-session-records",
    ),
    path(
        "sessions/<int:pk>/lock/",
        AttendanceLockAPIView.as_view(),
        name="attendance-session-lock",
    ),
    path(
        "sessions/<int:pk>/unlock/",
        AttendanceUnlockAPIView.as_view(),
        name="attendance-session-unlock",
    ),
]
