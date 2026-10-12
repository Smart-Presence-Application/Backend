from django.urls import path

from .views import ActivityLogListAPIView, MaintenanceAPIView, SystemStatusAPIView

app_name = "system"

urlpatterns = [
    path("status/", SystemStatusAPIView.as_view(), name="status"),
    path("maintenance/", MaintenanceAPIView.as_view(), name="maintenance"),
    path("logs/", ActivityLogListAPIView.as_view(), name="activity-logs"),
]
