from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from common.storage import (
    teacher_check_in_image_upload_path,
    teacher_check_out_image_upload_path,
)
from schools.models import School
from teachers.models import Teacher

MINUTES_PER_DAY = 24 * 60


class TeacherAttendanceStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    VERIFIED = "VERIFIED", "Verified"


class WorkDayType(models.TextChoices):
    FULL_DAY = "FULL_DAY", "Full day"
    HALF_DAY = "HALF_DAY", "Half day"
    ABSENT = "ABSENT", "Absent"


class TeacherAttendanceSettings(models.Model):
    """
    A school's rules for turning hours worked into days worked.

    Worked time at or above ``full_day_minutes`` is a full day, at or
    above ``half_day_minutes`` a half day, and anything less counts as
    absent. A school without a row uses the model defaults.
    """

    school = models.OneToOneField(
        School,
        on_delete=models.CASCADE,
        related_name="teacher_attendance_settings",
    )
    full_day_minutes = models.PositiveIntegerField(
        default=6 * 60,
        validators=[MinValueValidator(1), MaxValueValidator(MINUTES_PER_DAY)],
    )
    half_day_minutes = models.PositiveIntegerField(
        default=3 * 60,
        validators=[MinValueValidator(1), MaxValueValidator(MINUTES_PER_DAY)],
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teacher_attendance_settings"
        constraints = [
            models.CheckConstraint(
                condition=Q(half_day_minutes__lt=models.F("full_day_minutes")),
                name="half_day_shorter_than_full_day",
            ),
        ]

    def __str__(self) -> str:
        return f"Teacher attendance settings - {self.school}"

    def classify(self, worked_minutes: int) -> str:
        if worked_minutes >= self.full_day_minutes:
            return WorkDayType.FULL_DAY

        if worked_minutes >= self.half_day_minutes:
            return WorkDayType.HALF_DAY

        return WorkDayType.ABSENT


class TeacherAttendance(models.Model):
    """
    One teacher's school entry and exit on one day.

    The ``*_captured_at`` times are stamped by the server when the
    teacher's camera photo arrives and are never edited. On
    verification a School Admin may set ``*_verified_at`` to different
    times; the effective times are the verified ones when present.

    ``check_*_offline`` marks a photo queued on the device without
    internet: its time is the device's, so an admin should review it.
    ``worked_minutes`` and ``day_type`` are snapshotted at verification
    so later changes to the school's settings do not rewrite history.
    """

    teacher = models.ForeignKey(
        Teacher,
        on_delete=models.PROTECT,
        related_name="attendances",
    )
    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="teacher_attendances",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=TeacherAttendanceStatus.choices,
        default=TeacherAttendanceStatus.DRAFT,
    )

    check_in_captured_at = models.DateTimeField()
    check_in_image = models.ImageField(upload_to=teacher_check_in_image_upload_path)
    check_in_image_hash = models.CharField(max_length=64, unique=True)
    check_in_offline = models.BooleanField(default=False)

    check_out_captured_at = models.DateTimeField(null=True, blank=True)
    check_out_image = models.ImageField(
        upload_to=teacher_check_out_image_upload_path,
        null=True,
        blank=True,
    )
    check_out_image_hash = models.CharField(
        max_length=64,
        unique=True,
        null=True,
        blank=True,
    )
    check_out_offline = models.BooleanField(default=False)

    check_in_verified_at = models.DateTimeField(null=True, blank=True)
    check_out_verified_at = models.DateTimeField(null=True, blank=True)

    worked_minutes = models.PositiveIntegerField(null=True, blank=True)
    day_type = models.CharField(
        max_length=10,
        choices=WorkDayType.choices,
        null=True,
        blank=True,
    )
    day_type_overridden = models.BooleanField(default=False)

    remarks = models.CharField(max_length=255, blank=True, default="")
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    verified_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "teacher_attendances"
        ordering = ["-date", "teacher"]
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "date"],
                name="unique_teacher_attendance_per_day",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "date"],
                name="teacher_att_school_date_idx",
            ),
            models.Index(
                fields=["school", "status"],
                name="teacher_att_school_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.teacher} - {self.date} ({self.status})"

    @property
    def is_verified(self) -> bool:
        return self.status == TeacherAttendanceStatus.VERIFIED

    @property
    def check_in_at(self):
        return self.check_in_verified_at or self.check_in_captured_at

    @property
    def check_out_at(self):
        return self.check_out_verified_at or self.check_out_captured_at

    @property
    def current_worked_minutes(self) -> int | None:
        """
        Minutes between the effective check-in and check-out, or None
        while the teacher has not checked out.
        """

        if self.check_in_at is None or self.check_out_at is None:
            return None

        seconds = (self.check_out_at - self.check_in_at).total_seconds()
        return max(int(seconds // 60), 0)
