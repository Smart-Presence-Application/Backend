"""Content for the public website: testimonials, partner logos and contact enquiries."""

import uuid
from pathlib import Path

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from common.validators import validate_image_file


def _random_name(folder: str, filename: str) -> str:
    """A random file name, so a replaced image never comes back from a cache."""

    return f"website/{folder}/{uuid.uuid4().hex}{Path(filename).suffix.lower()}"


def testimonial_photo_path(instance, filename):
    return _random_name("testimonials", filename)


def partner_logo_path(instance, filename):
    return _random_name("partners", filename)


class Testimonial(models.Model):
    """
    A quote shown on the home page. Managed by Super Admins.

    ``role`` is e.g. "Principal" or "Parent of a Class 5 student";
    lower ``sort_order`` comes first.
    """

    name = models.CharField(max_length=120)
    role = models.CharField(max_length=120, blank=True, default="")
    organization = models.CharField(max_length=160, blank=True, default="")
    quote = models.TextField(max_length=600)
    rating = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    photo = models.ImageField(upload_to=testimonial_photo_path, blank=True, null=True, validators=[validate_image_file])
    is_published = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_testimonials"
        ordering = ["sort_order", "-created_at"]

    def __str__(self) -> str:
        return f"{self.name} ({self.organization})" if self.organization else self.name


class Partner(models.Model):
    """A partner's logo shown on the home page. Managed by Super Admins."""

    name = models.CharField(max_length=160)
    logo = models.ImageField(upload_to=partner_logo_path, validators=[validate_image_file])
    website = models.URLField(blank=True, default="")
    is_published = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "website_partners"
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class ContactMessage(models.Model):
    """
    An enquiry from the website's contact form. Kept even when the
    notification email fails, so no enquiry is lost.
    """

    name = models.CharField(max_length=120)
    email = models.EmailField()
    phone = models.CharField(max_length=20, blank=True, default="")
    school = models.CharField(max_length=160, blank=True, default="")
    message = models.TextField(max_length=3000)

    ip_address = models.CharField(max_length=64, blank=True, default="")
    user_agent = models.CharField(max_length=500, blank=True, default="")
    email_sent = models.BooleanField(default=False)
    is_read = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "website_contact_messages"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"
