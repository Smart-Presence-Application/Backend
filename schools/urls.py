from django.urls import path

from .views import (
    SchoolBulkDeleteAPIView,
    SchoolListCreateAPIView,
    SchoolDetailAPIView,
    SchoolStatusAPIView,
    MySchoolAPIView,
    MySchoolLogoAPIView,
)

urlpatterns = [
    path(
        "",
        SchoolListCreateAPIView.as_view(),
        name="school-list-create",
    ),
    path(
        "bulk-delete/",
        SchoolBulkDeleteAPIView.as_view(),
        name="school-bulk-delete",
    ),
    path(
        "<int:pk>/",
        SchoolDetailAPIView.as_view(),
        name="school-detail",
    ),
    path(
        "<int:pk>/status/",
        SchoolStatusAPIView.as_view(),
        name="school-status",
    ),
    
    path(
        "me/",
        MySchoolAPIView.as_view(),
        name="my-school",
    ),
    path(
        "me/logo/",
        MySchoolLogoAPIView.as_view(),
        name="my-school-logo",
    ),
]