from django.urls import path

from .views import (
    TeacherAssignmentAPIView,
    TeacherBulkUploadAPIView,
    TeacherDetailAPIView,
    TeacherListCreateAPIView,
    TeacherMeAPIView,
    TeacherStatusAPIView,
    TeacherTransferAPIView,
)

app_name = "teachers"

urlpatterns = [
    path(
        "me/",
        TeacherMeAPIView.as_view(),
        name="teacher-me",
    ),

    path(
        "bulk-upload/",
        TeacherBulkUploadAPIView.as_view(),
        name="teacher-bulk-upload",
    ),

    path(
        "",
        TeacherListCreateAPIView.as_view(),
        name="teacher-list-create",
    ),
    path(
        "<int:pk>/",
        TeacherDetailAPIView.as_view(),
        name="teacher-detail",
    ),
    path(
        "<int:pk>/status/",
        TeacherStatusAPIView.as_view(),
        name="teacher-status",
    ),
    path(
        "<int:pk>/class-section/",
        TeacherAssignmentAPIView.as_view(),
        name="teacher-class-section",
    ),
    path(
        "<int:pk>/transfer/",
        TeacherTransferAPIView.as_view(),
        name="teacher-transfer",
    ),
]
