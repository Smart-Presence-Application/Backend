import uuid

from django.conf import settings
from django.db import models

from academics.models import ClassSection
from common.choices import AttendanceStatus
from common.ordering import roll_order
from schools.models import School
from students.models import Student


class FaceRegistrationSource(models.TextChoices):
    PROFILE_IMAGE = "PROFILE_IMAGE", "Existing profile image"
    UPLOAD = "UPLOAD", "Uploaded image"


class SessionStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    LOCKED = "LOCKED", "Locked"


class RecordSource(models.TextChoices):
    AI = "AI", "AI verification"
    MANUAL = "MANUAL", "Manual"


class FaceRegistration(models.Model):
    """
    Marks that the AI service holds an embedding for a student.

    The embedding itself lives in the AI service; this row is our
    record of it. Verification only ever sends the student IDs that
    have a row here, so the two stores cannot silently drift apart in a
    way that changes attendance.
    """

    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        related_name="face_registration",
    )
    source = models.CharField(
        max_length=20,
        choices=FaceRegistrationSource.choices,
    )
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "face_registrations"
        ordering = ["-updated_at"]

    def __str__(self) -> str:
        return f"Face of {self.student}"


class AttendanceSession(models.Model):
    """
    One day's attendance for one class-section.

    A session starts as a DRAFT, which the assigned teacher may edit,
    and becomes LOCKED once the teacher confirms it. Only admins may
    change a locked session. ``image_count``, ``detected_faces`` and
    ``verified_at`` summarise the latest AI run for audit and the UI.
    """

    school = models.ForeignKey(
        School,
        on_delete=models.PROTECT,
        related_name="attendance_sessions",
    )
    class_section = models.ForeignKey(
        ClassSection,
        on_delete=models.PROTECT,
        related_name="attendance_sessions",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=SessionStatus.choices,
        default=SessionStatus.DRAFT,
    )

    image_count = models.PositiveIntegerField(default=0)
    detected_faces = models.PositiveIntegerField(default=0)
    verified_at = models.DateTimeField(null=True, blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "attendance_sessions"
        ordering = ["-date", "class_section"]
        constraints = [
            models.UniqueConstraint(
                fields=["class_section", "date"],
                name="unique_attendance_per_section_date",
            ),
        ]
        indexes = [
            models.Index(
                fields=["school", "date"],
                name="attendance_school_date_idx",
            ),
            models.Index(
                fields=["class_section", "date"],
                name="attendance_section_date_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.class_section} - {self.date} ({self.status})"

    @property
    def is_locked(self) -> bool:
        return self.status == SessionStatus.LOCKED


class AttendanceRecord(models.Model):
    """
    One student's attendance within a session.

    ``ai_status`` keeps what the AI said even after a person overrides
    ``status``, so a correction never erases the evidence. It is null
    when the student had no registered face and so was never checked.
    """

    session = models.ForeignKey(
        AttendanceSession,
        on_delete=models.CASCADE,
        related_name="records",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )

    status = models.CharField(
        max_length=10,
        choices=AttendanceStatus.choices,
        default=AttendanceStatus.ABSENT,
    )
    source = models.CharField(
        max_length=10,
        choices=RecordSource.choices,
        default=RecordSource.AI,
    )

    ai_status = models.CharField(
        max_length=10,
        choices=AttendanceStatus.choices,
        null=True,
        blank=True,
    )
    similarity = models.FloatField(null=True, blank=True)
    face_registered = models.BooleanField(default=False)

    remarks = models.CharField(
        max_length=255,
        blank=True,
        default="",
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
        db_table = "attendance_records"
        ordering = ["session", roll_order("student__roll_number")]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "student"],
                name="unique_student_per_attendance_session",
            ),
        ]
        indexes = [
            models.Index(
                fields=["student", "status"],
                name="attendance_student_status_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.student} - {self.session.date} - {self.status}"


class AIJobKind(models.TextChoices):
    FACE_REGISTER = "FACE_REGISTER", "Face registration from uploads"
    FACE_REGISTER_FROM_PROFILE = "FACE_REGISTER_FROM_PROFILE", "Face registration from profile images"
    STUDENT_PHOTO = "STUDENT_PHOTO", "Student photo and face"
    ATTENDANCE_VERIFY = "ATTENDANCE_VERIFY", "AI attendance verification"


class AIJobStatus(models.TextChoices):
    PENDING = "PENDING", "Queued"
    RUNNING = "RUNNING", "Running"
    SUCCEEDED = "SUCCEEDED", "Succeeded"
    FAILED = "FAILED", "Failed"


class AIJob(models.Model):
    """
    A piece of work that calls the AI service, run in the background.

    The AI service can take minutes, far longer than a request may stay
    open behind a production proxy, so the request only queues the work
    and answers 202 with this row. The client then polls it for
    progress and, once finished, its ``result`` or ``error``.

    ``updated_at`` doubles as a heartbeat: a job still active long after
    its last update belonged to a worker that died, and is reported as
    failed (see ``jobs.expire_if_stale``).

    ``student`` / ``class_section`` / ``date`` name what the job works
    on, so the same work is not queued twice. The counters give "x of y"
    progress while a batch runs. On failure, ``error``, ``error_status``
    and ``errors`` hold what the synchronous endpoint would have answered.
    """

    ACTIVE_STATUSES = (AIJobStatus.PENDING, AIJobStatus.RUNNING)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=40, choices=AIJobKind.choices)
    status = models.CharField(
        max_length=10,
        choices=AIJobStatus.choices,
        default=AIJobStatus.PENDING,
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="+",
    )

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    class_section = models.ForeignKey(
        ClassSection,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    date = models.DateField(null=True, blank=True)

    message = models.CharField(max_length=255, blank=True, default="")
    total = models.PositiveIntegerField(default=0)
    processed = models.PositiveIntegerField(default=0)
    succeeded = models.PositiveIntegerField(default=0)
    failed = models.PositiveIntegerField(default=0)

    result = models.JSONField(null=True, blank=True)

    error = models.TextField(blank=True, default="")
    error_status = models.PositiveSmallIntegerField(null=True, blank=True)
    errors = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ai_jobs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "updated_at"], name="ai_job_status_idx"),
            models.Index(fields=["created_at"], name="ai_job_created_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} ({self.status})"

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES
