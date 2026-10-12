from django.conf import settings
from django.db import models

from attendance_student.models import AttendanceRecord
from common.choices import AttendanceStatus
from students.models import Student


class Parent(models.Model):
    """
    A parent's login, linked to one or more students.

    Name and mobile number live on the user; the mobile number is the
    login. One parent account can be linked to several children, even
    across schools.

    ``initial_password`` keeps the system-generated password readable so
    staff can pass it on. It is cleared the moment the parent sets a
    password of their own (see signals), so a password the parent chose
    is never stored readably.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="parent_profile",
    )
    students = models.ManyToManyField(
        Student,
        related_name="parents",
        blank=True,
    )
    initial_password = models.CharField(
        max_length=128,
        blank=True,
        default="",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parents"
        ordering = ["user__name"]

    def __str__(self) -> str:
        return f"{self.user.name} ({self.user.phone_number})"

    @property
    def password_changed(self) -> bool:
        return not self.initial_password


class ParentNotification(models.Model):
    """
    An in-app message telling a parent their child's attendance.

    Deleting attendance (even after it was locked) withdraws the alerts sent
    about it, so a parent never sees attendance that no longer exists.
    """

    parent = models.ForeignKey(
        Parent,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name="+",
    )
    record = models.ForeignKey(
        AttendanceRecord,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="+",
    )
    date = models.DateField()
    status = models.CharField(
        max_length=10,
        choices=AttendanceStatus.choices,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "parent_notifications"
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["parent", "is_read"],
                name="parent_notif_unread_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.parent} - {self.title}"
