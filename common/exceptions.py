"""Custom exceptions and DRF exception handling."""
from django.core.exceptions import NON_FIELD_ERRORS
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.views import exception_handler
from common.responses import error_response

class AIServiceUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "AI service is currently unavailable."
    default_code = "ai_service_unavailable"


class DuplicateRecord(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "Duplicate record found."
    default_code = "duplicate_record"


def django_to_drf_validation_error(exc: DjangoValidationError) -> DRFValidationError:
    """Convert a model/service ValidationError into a DRF 400."""
    if hasattr(exc, "error_dict"):
        errors = exc.message_dict
        if NON_FIELD_ERRORS in errors:
            errors["non_field_errors"] = errors.pop(NON_FIELD_ERRORS)
        return DRFValidationError(errors)

    return DRFValidationError({"detail": exc.messages})


def custom_exception_handler(exc, context):
    """
    Wrap DRF errors in the standard response envelope.

    Services raise Django ValidationErrors (e.g. from full_clean); DRF does
    not handle those, so they are converted to a 400 first instead of
    surfacing as a 500.
    """
    if isinstance(exc, DjangoValidationError):
        exc = django_to_drf_validation_error(exc)

    response = exception_handler(exc, context)
    if response is None:
        return response
    
    if response.status_code == status.HTTP_401_UNAUTHORIZED:
        return error_response(
            "Authentication required.",
            response.data,
            status.HTTP_401_UNAUTHORIZED,
        )

    if response.status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        wait = getattr(exc, "wait", None)
        seconds = max(1, round(wait)) if wait else None
        throttled = error_response(
            f"Too many requests. Please try again in {seconds} second{'s' if seconds != 1 else ''}."
            if seconds
            else "Too many requests. Please try again shortly.",
            {"retry_after": seconds},
            status.HTTP_429_TOO_MANY_REQUESTS,
        )
        if "Retry-After" in response:
            throttled["Retry-After"] = response["Retry-After"]
        return throttled

    if response.status_code == status.HTTP_403_FORBIDDEN:
        return error_response(
            "Permission denied.",
            response.data,
            status.HTTP_403_FORBIDDEN,
        )
        
    detail = response.data

    message = detail.get("detail", "Request failed.")

    if isinstance(message, list):
        message = message[0]

    response.data = {
        "success": False,
        "message": str(message),
        "errors": detail,
    }
    return response


class AttendanceLocked(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Attendance is locked. Only an admin can change it now."
    )
    default_code = "attendance_locked"
