"""
Thin HTTP client for the external face-recognition service.

The service keys every embedding by ``school_id`` + ``student_id``.
We send the school's primary key and the student's school-unique
``student_id``, so the pair is unique across the whole platform.

Registration and verification run in background jobs (see jobs.py),
not inside a request, so the timeouts can be as long as the service
really needs.
"""

import logging
from dataclasses import dataclass

import requests
from decouple import config
from django.conf import settings

from common.exceptions import AIServiceUnavailable

logger = logging.getLogger(__name__)

AI_SERVICE_TIMEOUT = config("AI_SERVICE_TIMEOUT", default=300, cast=int)
AI_SERVICE_VERIFY_TIMEOUT = config(
    "AI_SERVICE_VERIFY_TIMEOUT",
    default=600,
    cast=int,
)


class AIServiceError(Exception):
    """
    The service understood the request but refused it.

    Raised for 4xx answers such as "no face detected", which the caller
    should report to the user rather than treat as an outage.
    """

    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class ImagePayload:
    name: str
    content: bytes
    content_type: str = "application/octet-stream"


def _url(path: str) -> str:
    return f"{settings.AI_SERVICE_URL.rstrip('/')}/{path.lstrip('/')}"


def _detail(response: requests.Response) -> str:
    """The service's error message, flattening FastAPI's list of validation errors."""

    try:
        detail = response.json().get("detail")
    except ValueError:
        detail = None

    if isinstance(detail, list):
        detail = "; ".join(
            str(item.get("msg", item)) if isinstance(item, dict) else str(item)
            for item in detail
        )

    return detail or response.text or "AI service rejected the request."


def _request(method: str, path: str, *, timeout: int, **kwargs) -> dict:
    """
    Call the AI service, sending the shared secret as X-AI-Service-Key when
    AI_SERVICE_API_KEY is set, and map failures to AIServiceUnavailable
    (network or 5xx) or AIServiceError (4xx).
    """
    headers = {"X-AI-Service-Key": settings.AI_SERVICE_API_KEY} if settings.AI_SERVICE_API_KEY else {}
    try:
        response = requests.request(
            method,
            _url(path),
            timeout=timeout,
            headers=headers,
            **kwargs,
        )
    except requests.RequestException as exc:
        logger.error("AI service %s %s failed: %s", method, path, exc)
        raise AIServiceUnavailable() from exc

    if response.status_code >= 500:
        logger.error(
            "AI service %s %s returned %s: %s",
            method,
            path,
            response.status_code,
            response.text[:500],
        )
        raise AIServiceUnavailable()

    if response.status_code >= 400:
        raise AIServiceError(_detail(response), response.status_code)

    try:
        return response.json()
    except ValueError as exc:
        logger.error("AI service %s %s returned non-JSON body", method, path)
        raise AIServiceUnavailable() from exc


def register_face(
    *,
    school_id: int | str,
    student_id: str,
    image: ImagePayload,
) -> dict:
    """
    Build and store the embedding for one student.

    The image must contain exactly one face. Any existing embedding for
    the student is replaced by the service.
    """

    return _request(
        "POST",
        "/register-face",
        timeout=AI_SERVICE_TIMEOUT,
        data={
            "school_id": str(school_id),
            "student_id": student_id,
        },
        files={
            "image": (image.name, image.content, image.content_type),
        },
    )


def verify_attendance(
    *,
    school_id: int | str,
    images: list[ImagePayload],
    student_ids: list[str] | None = None,
) -> dict:
    """
    Match the faces in ``images`` against registered embeddings.

    With ``student_ids`` the comparison is restricted to those
    students; without it the service searches the whole school. An
    empty list is treated as "no restriction" by the service, so the
    caller must never pass one when it means "nobody".
    """

    data = {"school_id": str(school_id)}

    if student_ids:
        data["student_ids"] = ",".join(student_ids)

    return _request(
        "POST",
        "/verify-attendance",
        timeout=AI_SERVICE_VERIFY_TIMEOUT,
        data=data,
        files=[
            ("images", (image.name, image.content, image.content_type))
            for image in images
        ],
    )


def delete_face(
    *,
    school_id: int | str,
    student_id: str,
) -> bool:
    """
    Remove a student's embedding.

    Returns False when the service had no embedding for the student,
    which callers can treat as success.
    """

    try:
        _request(
            "DELETE",
            "/delete-face",
            timeout=AI_SERVICE_TIMEOUT,
            data={
                "school_id": str(school_id),
                "student_id": student_id,
            },
        )
    except AIServiceError as exc:
        if exc.status_code == 404:
            return False

        raise

    return True


def delete_face_quietly(
    *,
    school_id: int | str,
    student_id: str,
) -> None:
    """
    Best-effort delete for use from signals and on-commit hooks.

    A failure is logged rather than raised: the local registration row
    is already gone, and verification only ever sends locally
    registered student IDs, so a stale embedding is never consulted.
    """

    try:
        delete_face(school_id=school_id, student_id=student_id)
    except (AIServiceUnavailable, AIServiceError) as exc:
        logger.warning(
            "Could not delete face embedding for school=%s student=%s: %s",
            school_id,
            student_id,
            exc,
        )
