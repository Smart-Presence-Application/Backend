from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.db import models
from django.utils import timezone

from common.validators import (
    validate_email,
    validate_image_file,
    validate_phone,
)
from common.choices import UserRole, Gender
from common.storage import user_profile_image_upload_path

class UserManager(BaseUserManager):
    use_in_migrations = True

    def create_user(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ):
        if not email:
            raise ValueError("The email address must be set.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        
        if user.is_active:
            from accounts.signals import user_created

            user_created.send(
                sender=self.model,
                user=user,
                raw_password=password,
            )

        return user

    def create_superuser(
        self,
        email: str,
        password: str | None = None,
        **extra_fields,
    ):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", UserRole.SUPER_ADMIN)
        extra_fields.setdefault("name", "Smart Presence Admin")

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")

        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self.create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """
    A person who can sign in.

    Email is optional only for parents, who sign in with their mobile number
    (Postgres allows many NULLs under a unique constraint). For the same
    reason a parent's mobile number must identify exactly one parent.
    """

    email = models.EmailField(
        unique=True,
        null=True,
        blank=True,
        validators=[validate_email],
    )
    name = models.CharField(max_length=150)
    phone_number = models.CharField(
        max_length=10,
        blank=True,
        validators=[validate_phone],
    )
    gender = models.CharField(
        max_length=10,
        choices=Gender.choices,
        default=Gender.OTHER,
    )
    profile_image = models.ImageField(
        upload_to=user_profile_image_upload_path,
        blank=True,
        null=True,
        validators=[validate_image_file],
    )
    role = models.CharField(
        max_length=20,
        choices=UserRole.choices,
        default=UserRole.TEACHER,
    )
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    date_joined = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["name"]

    class Meta:
        ordering = ["email"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=models.Q(role=UserRole.PARENT),
                name="unique_parent_phone_number",
            ),
        ]

    def __str__(self) -> str:
        return self.email or self.phone_number or f"User {self.pk}"