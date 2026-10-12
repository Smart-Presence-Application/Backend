from django.urls import path

from .views import (
    StudentBulkUploadAPIView,
    StudentDetailAPIView,
    StudentListCreateAPIView,
    StudentProfileImageAPIView,
    StudentPromoteAPIView,
)

app_name = "students"

urlpatterns = [
    path(
        "bulk-upload/",
        StudentBulkUploadAPIView.as_view(),
        name="student-bulk-upload",
    ),
    path(
        "promote/",
        StudentPromoteAPIView.as_view(),
        name="student-promote",
    ),
    path(
        "",
        StudentListCreateAPIView.as_view(),
        name="student-list-create",
    ),
    path(
        "<int:pk>/",
        StudentDetailAPIView.as_view(),
        name="student-detail",
    ),
    path(
        "<int:pk>/image/",
        StudentProfileImageAPIView.as_view(),
        name="student-profile-image",
    ),
]
