"""
Maintenance mode (503 for everyone but Super Admins) and the activity log.

``OPEN_PATHS`` stay reachable during maintenance so a Super Admin can
sign in and switch it off, apps can poll whether it is over, health
probes keep passing, and the public website stays up.
"""

import time

from django.http import JsonResponse

from accounts.authentication import CookieJWTAuthentication
from common.choices import UserRole

from .activity import login_identifier, record, should_log
from .services import maintenance_state

OPEN_PATHS = (
    "/api/system/health/",
    "/api/system/status/",
    "/api/auth/login/",
    "/api/auth/logout/",
    "/api/auth/refresh/",
    "/api/website/testimonials/",
    "/api/website/partners/",
    "/api/website/contact/",
)


def is_super_admin_request(request) -> bool | None:
    """
    None when the access token is expired or invalid: the request is let
    through so the API answers 401 and the app can refresh its session
    (then retry, and be told about maintenance if it is not a Super Admin).
    """

    try:
        result = CookieJWTAuthentication().authenticate(request)
    except Exception:
        return None

    if result is None:
        return False

    user = result[0]

    return bool(user and user.is_active and (user.is_superuser or user.role == UserRole.SUPER_ADMIN))


class MaintenanceModeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path

        if (
            path.startswith("/api/")
            and not path.startswith(OPEN_PATHS)
            and request.method != "OPTIONS"
        ):
            state = maintenance_state()

            if state["enabled"] and is_super_admin_request(request) is False:
                return JsonResponse(
                    {
                        "success": False,
                        "message": state["message"],
                        "errors": {"maintenance": True},
                    },
                    status=503,
                    headers={"Retry-After": "120"},
                )

        return self.get_response(request)


class ActivityLogMiddleware:
    """
    Record every create, update and delete (and sign-ins, sign-outs and
    report downloads) in the activity log for Super Admins to review.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        """
        The sign-in identifier is read from the body before the view does,
        so it is still available for a failed sign-in. DRF sets the
        authenticated user on the request while handling it.
        """

        if not should_log(request):
            return self.get_response(request)

        identifier = login_identifier(request) if request.path.endswith("/login/") else ""
        started = time.monotonic()

        response = self.get_response(request)

        record(request, response, identifier=identifier, duration_ms=int((time.monotonic() - started) * 1000))

        return response
