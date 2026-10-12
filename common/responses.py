"""Consistent API response helpers."""
from typing import Any

from rest_framework import status
from rest_framework.response import Response


def success_response(message: str, data: Any = None, status_code: int = status.HTTP_200_OK) -> Response:
    return Response({"success": True, "message": message, "data": data}, status=status_code)


def error_response(message: str, errors: Any = None, status_code: int = status.HTTP_400_BAD_REQUEST) -> Response:
    return Response({"success": False, "message": message, "errors": errors}, status=status_code)


def created_response(message: str = "Created successfully.", data: Any = None) -> Response:
    return success_response(message, data, status.HTTP_201_CREATED)


def accepted_response(message: str, data: Any = None) -> Response:
    """Work was queued to run in the background; ``data`` says how to follow it."""
    return success_response(message, data, status.HTTP_202_ACCEPTED)


def updated_response(message: str = "Updated successfully.", data: Any = None) -> Response:
    return success_response(message, data, status.HTTP_200_OK)


def deleted_response(message: str = "Deleted successfully.", data: Any = None) -> Response:
    return success_response(message, data, status.HTTP_200_OK)


def paginated_response(message: str = "Fetched successfully.", *, results: Any, count: int, next_url: str | None = None, previous_url: str | None = None) -> Response:
    return success_response(
        message,
        {"count": count, "next": next_url, "previous": previous_url, "results": results},
        status.HTTP_200_OK,
    )

def not_found_response(
    message: str = "Resource not found.", errors: Any = None
) -> Response:
    return error_response(
        message=message,
        errors=errors,
        status_code=status.HTTP_404_NOT_FOUND,
    )