from django.conf import settings
from django.db import models

from common.choices import Status
from common.validators import (
    validate_email,
    validate_logo,
    validate_phone,
)
from django.core.validators import MinValueValidator, MaxValueValidator
from common.storage import school_logo_upload_path

class School(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=50, unique=True)

    email = models.EmailField(
        unique=True,
        validators=[validate_email],
    )

    phone = models.CharField(
        max_length=10,
        validators=[validate_phone],
    )

    address = models.TextField()
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100)
    pincode = models.CharField(max_length=20)

    logo = models.ImageField(
        upload_to=school_logo_upload_path,
        blank=True,
        null=True,
        validators=[validate_logo],
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.INACTIVE,
    )

    admin = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="managed_school",
    )
    
    attendance_threshold = models.PositiveIntegerField(
        default=75,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(100),
        ],
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "schools"
        ordering = ("name", "-created_at",)
        verbose_name = "School"
        verbose_name_plural = "Schools"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["city"]),
            models.Index(fields=["state"]),
        ]
        
    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"