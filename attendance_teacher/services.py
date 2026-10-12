"""Business logic for teacher check-in / check-out attendance."""

import logging
from datetime import datetime, time
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from notifications.push import send_push
from schools.models import School
from teachers.models import Teacher

from .capture import image_sha256, validate_live_capture
from .models import (
    TeacherAttendance,
    TeacherAttendanceSettings,
    TeacherAttendanceStatus,
    WorkDayType,
)

logger = logging.getLogger(__name__)

DUPLICATE_IMAGE_MESSAGE = (
    "This photo has already been used. Please take a new photo with the camera."
)


def get_attendance_settings(school: School) -> TeacherAttendanceSettings:
    """
    The school's settings, or unsaved defaults if it has none yet.
    """

    found = TeacherAttendanceSettings.objects.filter(school=school).first()
    return found or TeacherAttendanceSettings(school=school)


def update_attendance_settings(
    *,
    school: School,
    actor,
    validated_data: dict[str, Any],
) -> TeacherAttendanceSettings:
    current = get_attendance_settings(school)

    for field, value in validated_data.items():
        setattr(current, field, value)

    if current.half_day_minutes >= current.full_day_minutes:
        raise ValidationError(
            {"half_day_minutes": "A half day must be shorter than a full day."}
        )

    current.updated_by = actor
    current.full_clean()
    current.save()

    return current


def _ensure_unused_image(image_hash: str) -> None:
    if TeacherAttendance.objects.filter(
        Q(check_in_image_hash=image_hash) | Q(check_out_image_hash=image_hash)
    ).exists():
        raise ValidationError({"image": DUPLICATE_IMAGE_MESSAGE})


def _capture_moment(captured_at: datetime, offline: bool) -> datetime:
    """
    The time to record: the server's clock online, so a wrong device
    clock cannot move it; the device's capture time for an offline
    photo synced later, which is why such days are flagged for review.
    """

    return captured_at if offline else timezone.now()


def _notify_admin(attendance: TeacherAttendance, action: str, moment: datetime, offline: bool) -> None:
    """
    Tell the school admin a day is waiting for verification.
    """

    when = timezone.localtime(moment).strftime("%I:%M %p").lstrip("0")
    send_push(
        [attendance.school.admin_id],
        title=f"{attendance.teacher.user.name} {action}",
        body=f"At {when}" + (" (synced from offline)" if offline else "") + ". Awaiting your verification.",
        path="teacher-attendance?status=DRAFT",
        tag=f"teacher-attendance-{attendance.pk}",
    )


def check_in(
    *,
    teacher: Teacher,
    image,
    captured_at: datetime,
    offline: bool = False,
) -> TeacherAttendance:
    """
    Record the teacher's school entry as a draft, for the day the photo
    was taken. A unique constraint catches a double-tap that races past
    the checks.
    """

    validate_live_capture(file_obj=image, captured_at=captured_at, now=timezone.now(), offline=offline)

    now = _capture_moment(captured_at, offline)
    today = timezone.localdate(now)

    image_hash = image_sha256(image)
    _ensure_unused_image(image_hash)

    if TeacherAttendance.objects.filter(teacher=teacher, date=today).exists():
        raise ValidationError({"detail": "You have already checked in today."})

    try:
        with transaction.atomic():
            attendance = TeacherAttendance.objects.create(
                teacher=teacher,
                school_id=teacher.school_id,
                date=today,
                check_in_captured_at=now,
                check_in_image=image,
                check_in_image_hash=image_hash,
                check_in_offline=offline,
            )
    except IntegrityError as exc:
        raise ValidationError({"detail": "You have already checked in today."}) from exc

    logger.info("Teacher %s checked in at %s%s", teacher.employee_id, now, " (offline)" if offline else "")
    _notify_admin(attendance, "checked in", now, offline)

    return attendance


def check_out(
    *,
    teacher: Teacher,
    image,
    captured_at: datetime,
    offline: bool = False,
) -> TeacherAttendance:
    """
    Record the teacher's school exit on the draft for the day the photo
    was taken.
    """

    validate_live_capture(file_obj=image, captured_at=captured_at, now=timezone.now(), offline=offline)

    now = _capture_moment(captured_at, offline)
    today = timezone.localdate(now)

    image_hash = image_sha256(image)
    _ensure_unused_image(image_hash)

    with transaction.atomic():
        attendance = (
            TeacherAttendance.objects.select_for_update()
            .filter(teacher=teacher, date=today)
            .first()
        )

        if attendance is None:
            raise ValidationError({"detail": "You have not checked in today."})

        if attendance.check_out_captured_at is not None:
            raise ValidationError({"detail": "You have already checked out today."})

        if attendance.is_verified:
            raise ValidationError(
                {"detail": "Today's attendance has already been verified by the school admin."}
            )

        if now <= attendance.check_in_captured_at:
            raise ValidationError({"captured_at": "Check-out must be after check-in."})

        attendance.check_out_captured_at = now
        attendance.check_out_image = image
        attendance.check_out_image_hash = image_hash
        attendance.check_out_offline = offline

        try:
            with transaction.atomic():
                attendance.save()
        except IntegrityError as exc:
            raise ValidationError({"image": DUPLICATE_IMAGE_MESSAGE}) from exc

    logger.info("Teacher %s checked out at %s%s", teacher.employee_id, now, " (offline)" if offline else "")
    _notify_admin(attendance, "checked out", now, offline)

    return attendance


def _on_record_date(attendance: TeacherAttendance, value: time | None):
    if value is None:
        return None

    return timezone.make_aware(datetime.combine(attendance.date, value))


@transaction.atomic
def verify_attendance(
    *,
    attendance: TeacherAttendance,
    actor,
    check_in_time: time | None = None,
    check_out_time: time | None = None,
    day_type: str | None = None,
    remarks: str | None = None,
) -> TeacherAttendance:
    """
    Finalise a teacher's day.

    The admin may set different check-in / check-out times (e.g. to give
    credit for time spent on school duty outside the building) and may
    mark the day as a half or full day directly. Otherwise the day type
    comes from the school's settings. The captured times are kept
    unchanged for audit.

    A verified day can be verified again to correct it.
    """

    attendance = TeacherAttendance.objects.select_for_update().get(pk=attendance.pk)

    if check_in_time is not None:
        attendance.check_in_verified_at = _on_record_date(attendance, check_in_time)

    if check_out_time is not None:
        attendance.check_out_verified_at = _on_record_date(attendance, check_out_time)

    if attendance.check_out_at is None:
        raise ValidationError(
            {
                "check_out_time": (
                    "The teacher has not checked out. Enter a check-out "
                    "time to verify this day."
                )
            }
        )

    if attendance.check_out_at <= attendance.check_in_at:
        raise ValidationError({"check_out_time": "Check-out must be after check-in."})

    worked = attendance.current_worked_minutes

    if day_type:
        attendance.day_type = day_type
        attendance.day_type_overridden = True
    else:
        attendance.day_type = get_attendance_settings(attendance.school).classify(worked)
        attendance.day_type_overridden = False

    if remarks is not None:
        attendance.remarks = remarks

    attendance.worked_minutes = worked
    attendance.status = TeacherAttendanceStatus.VERIFIED
    attendance.verified_by = actor
    attendance.verified_at = timezone.now()
    attendance.save()

    send_push(
        [attendance.teacher.user_id],
        title="Your attendance was verified",
        body=f"{attendance.date:%d %b %Y}: {attendance.get_day_type_display()}.",
        path="my-attendance",
        tag=f"teacher-attendance-{attendance.pk}",
    )

    logger.info(
        "Teacher attendance %s verified by user %s as %s (%s min)",
        attendance.pk,
        actor.pk,
        attendance.day_type,
        worked,
    )

    return attendance


def _hours(minutes: int) -> float:
    return float(
        (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    )


def summarise(queryset: QuerySet[TeacherAttendance]) -> list[dict[str, Any]]:
    """
    Per-teacher totals over ``queryset``.

    Only verified days count towards hours and days; drafts are
    reported separately as ``pending_verification``. Two half days make
    one working day.
    """

    verified = Q(status=TeacherAttendanceStatus.VERIFIED)

    rows = (
        queryset.order_by()
        .values(
            "teacher_id",
            "teacher__employee_id",
            "teacher__user__name",
        )
        .annotate(
            worked_minutes_total=Sum("worked_minutes", filter=verified, default=0),
            full_days=Count("id", filter=verified & Q(day_type=WorkDayType.FULL_DAY)),
            half_days=Count("id", filter=verified & Q(day_type=WorkDayType.HALF_DAY)),
            absent_days=Count("id", filter=verified & Q(day_type=WorkDayType.ABSENT)),
            pending_verification=Count(
                "id",
                filter=Q(status=TeacherAttendanceStatus.DRAFT),
            ),
        )
        .order_by("teacher__employee_id")
    )

    return [
        {
            "teacher": row["teacher_id"],
            "employee_id": row["teacher__employee_id"],
            "teacher_name": row["teacher__user__name"],
            "total_working_minutes": row["worked_minutes_total"],
            "total_working_hours": _hours(row["worked_minutes_total"]),
            "total_full_days": row["full_days"],
            "total_half_days": row["half_days"],
            "total_absent_days": row["absent_days"],
            "total_working_days": row["full_days"] + row["half_days"] / 2,
            "pending_verification": row["pending_verification"],
        }
        for row in rows
    ]


def _delete_files(*files) -> None:
    for file in files:
        if file:
            file.delete(save=False)


@transaction.atomic
def delete_attendance(*, attendance: TeacherAttendance, actor) -> None:
    """
    Delete a teacher's day, draft or verified, along with its photos.

    The photos are removed only once the transaction commits, so a
    rollback never leaves a row pointing at missing files.
    """

    attendance = TeacherAttendance.objects.select_for_update().get(pk=attendance.pk)
    attendance_id = attendance.pk
    images = (attendance.check_in_image, attendance.check_out_image)

    attendance.delete()

    transaction.on_commit(lambda: _delete_files(*images))

    logger.info("Teacher attendance %s deleted by user %s", attendance_id, actor.pk)
