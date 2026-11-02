from django.urls import path

from .views import ActivityLogListAPIView, HealthAPIView, MaintenanceAPIView, ServicesStatusAPIView, SystemStatusAPIView

app_name = "system"

urlpatterns = [
    path("health/", HealthAPIView.as_view(), name="health"),
    path("status/", SystemStatusAPIView.as_view(), name="status"),
    path("services/", ServicesStatusAPIView.as_view(), name="services"),
    path("maintenance/", MaintenanceAPIView.as_view(), name="maintenance"),
    path("logs/", ActivityLogListAPIView.as_view(), name="activity-logs"),
]
