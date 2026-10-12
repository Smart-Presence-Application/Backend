from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.permissions import AllowAny, IsAuthenticated

from common.pagination import StandardResultsPagination
from common.permissions import IsSuperAdmin
from common.responses import success_response, updated_response

from . import services
from .filters import ActivityLogFilter
from .models import ActivityLog
from .serializers import ActivityLogSerializer, MaintenanceSettingsSerializer


class SystemStatusAPIView(generics.GenericAPIView):
    """
    Public: whether the platform is in maintenance, so apps can show the
    maintenance screen and notice when it is over.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        state = services.maintenance_state()

        return success_response(
            "Status fetched successfully.",
            {"maintenance": state["enabled"], "message": state["message"] if state["enabled"] else ""},
        )


class MaintenanceAPIView(generics.GenericAPIView):
    """
    Super Admins read and switch maintenance mode. Super Admins keep
    full access while it is on; everyone else gets the maintenance screen.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = MaintenanceSettingsSerializer

    def get(self, request, *args, **kwargs):
        return success_response(
            "Maintenance settings fetched successfully.",
            self.get_serializer(services.get_settings()).data,
        )

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)

        row = services.set_maintenance(actor=request.user, **serializer.validated_data)

        return updated_response(
            "Maintenance mode is on." if row.is_enabled else "Maintenance mode is off.",
            self.get_serializer(row).data,
        )


class ActivityLogListAPIView(generics.ListAPIView):
    """
    Super Admins review what everyone did: newest first, searchable by
    person, action, path or IP, and filterable by role, school, category,
    outcome and date.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = ActivityLogSerializer
    pagination_class = StandardResultsPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_class = ActivityLogFilter
    search_fields = ["actor_name", "actor_identifier", "school_name", "action", "path", "ip_address"]

    def get_queryset(self):
        return ActivityLog.objects.all()
