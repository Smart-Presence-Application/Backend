"""
Background runner for work that calls the AI service.

Face registration and attendance verification can keep the AI service
busy for minutes, far longer than a production proxy keeps a request
open. Endpoints therefore validate what they can straight away, queue
the slow part here, and answer 202 with an ``AIJob`` the client polls.

Jobs run on a small thread pool inside the web process, so no broker or
extra worker process is needed. The job row in the database is the only
shared state, so a poll can land on any worker. A job whose process dies
(deploy, restart) stops updating and is reported as failed once stale.

Uploaded files are read into memory before the request ends: Django
deletes temporary upload files once the response is sent.
"""

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any, Callable

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connections, transaction
from django.utils import timezone
from rest_framework.exceptions import APIException

from common.exceptions import AIServiceUnavailable

from .ai_client import AIServiceError
from .models import AIJob, AIJobStatus

logger = logging.getLogger(__name__)

_executor: ThreadPoolExecutor | None = None


def _get_executor() -> ThreadPoolExecutor:
    global _executor

    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=settings.AI_JOB_WORKERS,
            thread_name_prefix="ai-job",
        )

    return _executor


def detach_upload(file_obj) -> SimpleUploadedFile:
    """
    An in-memory copy of an upload that outlives the request.
    """

    file_obj.seek(0)
    content = file_obj.read()
    file_obj.seek(0)

    return SimpleUploadedFile(
        file_obj.name,
        content,
        content_type=getattr(file_obj, "content_type", None),
    )


class JobProgress:
    """
    Handed to the work function to report how far it got.

    Every update also refreshes ``updated_at``, the job's heartbeat.
    """

    def __init__(self, job_id):
        self.job_id = job_id

    def update(self, **fields) -> None:
        fields["updated_at"] = timezone.now()
        AIJob.objects.filter(pk=self.job_id).update(**fields)

    def stage(self, message: str) -> None:
        self.update(message=message[:255])


def _failure(exc: Exception) -> dict[str, Any]:
    """
    The error fields for ``exc``, matching what the endpoint answered
    when it still did the work inside the request. Any APIException
    (AIServiceUnavailable 503, AttendanceLocked 409, ...) keeps its status.
    """

    if isinstance(exc, AIServiceError):
        return {
            "error": exc.message,
            "error_status": 400,
            "errors": {"ai_service": exc.message},
        }

    if isinstance(exc, DjangoValidationError):
        errors = exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}
        return {
            "error": "; ".join(exc.messages),
            "error_status": 400,
            "errors": errors,
        }

    if isinstance(exc, APIException):
        detail = exc.detail if isinstance(exc.detail, (dict, list)) else str(exc.detail)
        return {
            "error": str(detail if isinstance(detail, str) else exc.default_detail),
            "error_status": exc.status_code,
            "errors": {"detail": detail, "code": exc.default_code},
        }

    return {
        "error": "Something went wrong while processing. Please try again.",
        "error_status": 500,
        "errors": None,
    }


def _run(job_id, work: Callable[[JobProgress], Any]) -> None:
    progress = JobProgress(job_id)

    try:
        progress.update(status=AIJobStatus.RUNNING, started_at=timezone.now())
        result = work(progress)
    except Exception as exc:
        if not isinstance(exc, (AIServiceError, AIServiceUnavailable, DjangoValidationError, APIException)):
            logger.exception("AI job %s crashed", job_id)
        else:
            logger.info("AI job %s failed: %s", job_id, exc)

        progress.update(
            status=AIJobStatus.FAILED,
            finished_at=timezone.now(),
            **_failure(exc),
        )
    else:
        progress.update(
            status=AIJobStatus.SUCCEEDED,
            finished_at=timezone.now(),
            result=result,
        )
        logger.info("AI job %s succeeded", job_id)


def _run_in_thread(job_id, work) -> None:
    """Run the job, then close this thread's connections since the pool reuses it."""

    try:
        _run(job_id, work)
    finally:
        connections.close_all()


def start_job(
    *,
    kind: str,
    actor,
    work: Callable[[JobProgress], Any],
    message: str = "Queued.",
    **fields,
) -> AIJob:
    """
    Record a job and queue ``work(progress)`` to run in the background.

    ``work`` returns the JSON-serialisable result, or raises to fail the
    job. It must not rely on objects loaded by the request beyond plain
    values: it runs in another thread with its own database connection.

    The job is queued once the surrounding transaction commits, so the
    worker always sees what the request wrote. With
    ``AI_JOBS_RUN_INLINE`` (tests) it runs before this returns.
    """

    _prune_old_jobs()

    job = AIJob.objects.create(
        kind=kind,
        created_by=actor,
        message=message,
        **fields,
    )

    if settings.AI_JOBS_RUN_INLINE:
        _run(job.pk, work)
        job.refresh_from_db()
    else:
        transaction.on_commit(
            lambda: _get_executor().submit(_run_in_thread, job.pk, work)
        )

    return job


def _stale_before():
    return timezone.now() - timedelta(seconds=settings.AI_JOB_STALE_AFTER)


def active_jobs():
    """Jobs still queued or running that have not gone stale."""

    return AIJob.objects.filter(
        status__in=AIJob.ACTIVE_STATUSES,
        updated_at__gte=_stale_before(),
    )


def expire_if_stale(job: AIJob) -> AIJob:
    """
    Fail a job whose worker stopped reporting, e.g. after a restart.
    """

    if job.is_active and job.updated_at < _stale_before():
        AIJob.objects.filter(pk=job.pk, status__in=AIJob.ACTIVE_STATUSES).update(
            status=AIJobStatus.FAILED,
            finished_at=timezone.now(),
            error="Processing was interrupted (the server restarted). Please try again.",
            error_status=503,
            errors={"detail": "interrupted"},
        )
        job.refresh_from_db()

    return job


def _prune_old_jobs() -> None:
    cutoff = timezone.now() - timedelta(days=settings.AI_JOB_RETENTION_DAYS)
    AIJob.objects.filter(created_at__lt=cutoff).delete()
