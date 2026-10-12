"""Excel report downloads."""

from django.utils import timezone
from rest_framework import generics
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated

from common.permissions import IsStudentManager
from common.responses import success_response

from .excel import xlsx_response
from .exports import ALL_KEY, REPORTS, build_report, reports_for
from .serializers import ReportFilterSerializer


class ReportListAPIView(generics.GenericAPIView):
    """
    The reports the signed-in user may download, with the filters each
    one understands. Super Admins get all of them, School Admins all
    but the cross-school ones, and teachers their own class's students,
    parents and attendance.
    """

    permission_classes = [IsAuthenticated, IsStudentManager]

    def get(self, request, *args, **kwargs):
        reports = reports_for(request.user)

        return success_response(
            "Reports fetched successfully.",
            [
                {
                    "key": report.key,
                    "title": report.title,
                    "description": report.description,
                    "filters": list(report.filters),
                }
                for report in reports
            ],
        )


class ReportDownloadAPIView(generics.GenericAPIView):
    """
    Download a report as .xlsx. ``all`` bundles every report the user
    may see into one workbook, a sheet (or two) each. Unknown and
    forbidden reports both answer 404, so nothing is revealed.
    """

    permission_classes = [IsAuthenticated, IsStudentManager]
    serializer_class = ReportFilterSerializer

    def get(self, request, key, *args, **kwargs):
        allowed = {report.key for report in reports_for(request.user)}

        if key != ALL_KEY and key not in allowed:
            raise NotFound("Report not found.")

        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        sheets = build_report(request.user, key, serializer.validated_data)
        name = "all-data" if key == ALL_KEY else REPORTS[key].key
        stamp = timezone.localtime().strftime("%Y%m%d-%H%M")

        return xlsx_response(f"smartpresence-{name}-{stamp}.xlsx", sheets)
