from django.conf import settings
from django.db import models

DEFAULT_MESSAGE = (
    "SmartPresence is undergoing scheduled maintenance. "
    "We'll be back shortly - thank you for your patience."
)


class MaintenanceSettings(models.Model):
    """
    Whether the platform is in maintenance mode. A single row (pk=1),
    switched by Super Admins; while on, everyone else is shown the
    maintenance screen.
    """

    is_enabled = models.BooleanField(default=False)
    message = models.CharField(max_length=500, blank=True, default="")
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "maintenance_settings"
        verbose_name = "Maintenance settings"
        verbose_name_plural = "Maintenance settings"

    def __str__(self) -> str:
        return f"Maintenance {'on' if self.is_enabled else 'off'}"

    @property
    def display_message(self) -> str:
        return self.message or DEFAULT_MESSAGE


class ActivityLog(models.Model):
    """
    One recorded API action: who did what, when, from where, and whether
    it worked. Written by system.middleware.ActivityLogMiddleware.

    The actor's name, role and school are copied in, so the log still reads
    correctly after the account or school is changed or deleted.
    ``actor_identifier`` is the email or mobile number; for a failed
    sign-in, what was typed. ``action`` describes what happened in words
    ("Updated student"), next to the raw request fields.
    """

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    actor_name = models.CharField(max_length=255, blank=True, default="")
    actor_identifier = models.CharField(max_length=255, blank=True, default="")
    actor_role = models.CharField(max_length=20, blank=True, default="")
    school = models.ForeignKey(
        "schools.School",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    school_name = models.CharField(max_length=255, blank=True, default="")

    action = models.CharField(max_length=255)
    category = models.CharField(max_length=50, db_index=True)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    status_code = models.PositiveSmallIntegerField()
    duration_ms = models.PositiveIntegerField(default=0)

    ip_address = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=500, blank=True, default="")

    class Meta:
        db_table = "activity_logs"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["actor", "created_at"], name="activity_actor_time_idx"),
            models.Index(fields=["school", "created_at"], name="activity_school_time_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.actor_name or 'Anonymous'}: {self.action}"

    @property
    def succeeded(self) -> bool:
        return self.status_code < 400
