from django.urls import path

from .views import ReportDownloadAPIView, ReportListAPIView

app_name = "reports"

urlpatterns = [
    path("", ReportListAPIView.as_view(), name="report-list"),
    path("<slug:key>/", ReportDownloadAPIView.as_view(), name="report-download"),
]
