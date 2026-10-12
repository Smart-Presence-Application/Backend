"""Shared validators."""
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import EmailValidator, RegexValidator

from decouple import config

PASSWORD_LENGTH = config("PASSWORD_LENGTH", default=12, cast=int)
PHONE_LENGTH = config("PHONE_LENGTH", default=10, cast=int)

validate_email = EmailValidator(message="Enter a valid email address.")
validate_phone = RegexValidator(regex=rf"^\d{{{PHONE_LENGTH}}}$", message=f"Enter a valid {PHONE_LENGTH}-digit phone number.")


def validate_password_strength(password: str) -> None:
    if len(password) < PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {PASSWORD_LENGTH} characters long.")
    if password.isdigit() or password.isalpha():
        raise ValidationError("Password must contain a mix of letters, numbers, or symbols.")


def validate_csv_file(file_obj) -> None:
    if Path(file_obj.name).suffix.lower() != ".csv":
        raise ValidationError("Only CSV files are allowed.")


def validate_image_file(file_obj) -> None:
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    if Path(file_obj.name).suffix.lower() not in allowed:
        raise ValidationError("Only JPG, PNG, or WEBP image files are allowed.")


def validate_logo(logo):
    """
    Validate an uploaded logo image.

    Only freshly uploaded files carry a content type; stored files were
    already checked when they were uploaded.
    """
    if logo is None:
        return logo

    content_type = getattr(logo, "content_type", None)

    if content_type and not content_type.startswith("image/"):
        raise ValidationError("Only image files are allowed.")

    return logo