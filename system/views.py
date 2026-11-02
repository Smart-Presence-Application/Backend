import time

import requests
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, generics
from rest_framework.permissions import AllowAny, IsAuthenticated

from common.pagination import StandardResultsPagination
from common.permissions import IsSuperAdmin
from common.responses import error_response, success_response, updated_response

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


def _check(probe) -> dict:
    started = time.monotonic()

    try:
        probe()
    except Exception as exc:
        return {"ok": False, "error": exc.__class__.__name__}

    return {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000, 1)}


def _probe_database():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def _probe_cache():
    cache.set("system:health", "ok", 5)

    if cache.get("system:health") != "ok":
        raise RuntimeError("cache read-back failed")


class HealthAPIView(generics.GenericAPIView):
    """
    Public liveness/readiness probe for load balancers and uptime monitors:
    200 when the database and cache answer, 503 otherwise. Stays reachable
    during maintenance and reports whether it is on.
    """

    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = []

    def get(self, request, *args, **kwargs):
        checks = {"database": _check(_probe_database), "cache": _check(_probe_cache)}
        healthy = all(check["ok"] for check in checks.values())
        data = {
            "status": "ok" if healthy else "unhealthy",
            "maintenance": services.maintenance_state()["enabled"] if checks["database"]["ok"] else None,
            "checks": checks,
        }

        if not healthy:
            return error_response("Service is unhealthy.", data, status_code=503)

        return success_response("Service is healthy.", data)


SERVICES_CACHE_SECONDS = 15
AI_HEALTH_TIMEOUT = 4


def _probe_ai_service() -> tuple[dict, dict]:
    """
    The AI service's own health check, which also reports whether its
    MongoDB answers. MongoDB counts as unknown when the AI service is down.
    """

    started = time.monotonic()

    try:
        response = requests.get(f"{settings.AI_SERVICE_URL.rstrip('/')}/health", timeout=AI_HEALTH_TIMEOUT)
        response.raise_for_status()
        body = response.json()
    except Exception as exc:
        down = {"ok": False, "error": exc.__class__.__name__}
        return down, {"ok": None, "error": "AI service unreachable"}

    ai = {"ok": True, "latency_ms": round((time.monotonic() - started) * 1000, 1), "model_loaded": bool(body.get("model_loaded"))}
    mongo_state = body.get("database")
    mongodb = {"ok": None} if mongo_state is None else {"ok": mongo_state == "ok"}

    return ai, mongodb


class ServicesStatusAPIView(generics.GenericAPIView):
    """
    Public: the state of each part of the platform for the status page,
    and the maintenance notice when maintenance is on. Cached briefly so
    the page can be refreshed freely. Reachable during maintenance.
    """

    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, *args, **kwargs):
        data = cache.get(services.SERVICES_CACHE_KEY)

        if data is None:
            postgres = _check(_probe_database)
            ai_service, mongodb = _probe_ai_service()
            maintenance = None

            if postgres["ok"]:
                row = services.get_settings()
                maintenance = {
                    "enabled": row.is_enabled,
                    "message": row.display_message if row.is_enabled else "",
                    "updated_at": row.updated_at.isoformat() if row.is_enabled else None,
                }

            data = {
                "services": {
                    "backend": {"ok": True},
                    "postgres": postgres,
                    "ai_service": ai_service,
                    "mongodb": mongodb,
                },
                "maintenance": maintenance,
                "checked_at": timezone.now().isoformat(),
            }
            cache.set(services.SERVICES_CACHE_KEY, data, SERVICES_CACHE_SECONDS)

        return success_response("Service status fetched successfully.", data)


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
