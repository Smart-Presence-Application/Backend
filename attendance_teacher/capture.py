"""
Checks that a check-in photo was taken just now, not picked from a
gallery.

A server cannot prove an image came from a live camera; the frontend
must open the camera (getUserMedia, or <input capture>) and never offer
a file picker. What the server enforces is everything it can check:

* the time recorded is the server's own clock, never the client's;
* the client's ``captured_at`` must be within a few minutes of now;
* if the photo carries an EXIF capture time, it must be recent too,
  which catches most old gallery photos;
* the exact same image can never be used twice (SHA-256 of the bytes).

Offline captures (the app queued the photo with no internet) are the
exception: they may be up to ``OFFLINE_MAX_CAPTURE_HOURS`` old, the
recorded time is the device's capture time, and the day is flagged so
the school admin reviews it before verifying.
"""

import hashlib
from datetime import datetime

from decouple import config
from django.core.exceptions import ValidationError
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

MAX_CAPTURE_SKEW_SECONDS = config("MAX_CAPTURE_SKEW_SECONDS", default=120, cast=int)
OFFLINE_MAX_CAPTURE_HOURS = config("OFFLINE_MAX_CAPTURE_HOURS", default=12, cast=int)

EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME = 306


def image_sha256(file_obj) -> str:
    file_obj.seek(0)
    digest = hashlib.sha256()

    for chunk in iter(lambda: file_obj.read(64 * 1024), b""):
        digest.update(chunk)

    file_obj.seek(0)
    return digest.hexdigest()


def _exif_taken_at(file_obj) -> datetime | None:
    """The EXIF capture time, read as local time since cameras write it without a zone."""

    file_obj.seek(0)

    try:
        with Image.open(file_obj) as image:
            exif = image.getexif()
            raw = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(
                EXIF_DATETIME
            )
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError({"image": "The image could not be read."}) from exc
    finally:
        file_obj.seek(0)

    if not raw:
        return None

    try:
        naive = datetime.strptime(str(raw).strip("\x00 "), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None

    return timezone.make_aware(naive)


def validate_live_capture(*, file_obj, captured_at: datetime, now: datetime, offline: bool = False) -> None:
    """
    Reject photos that were not just taken.

    Online, ``captured_at`` must be within a couple of minutes of now.
    Offline, it may be up to ``OFFLINE_MAX_CAPTURE_HOURS`` in the past
    (never in the future), and an EXIF time must agree with the claimed
    capture time.
    """

    age = (now - captured_at).total_seconds()

    if offline:
        if age < -MAX_CAPTURE_SKEW_SECONDS:
            raise ValidationError({"captured_at": "The capture time is in the future. Check the device clock."})

        if age > OFFLINE_MAX_CAPTURE_HOURS * 3600:
            raise ValidationError(
                {
                    "captured_at": (
                        f"Offline photos must be uploaded within {OFFLINE_MAX_CAPTURE_HOURS} hours. "
                        "Please take a new photo."
                    )
                }
            )
    elif abs(age) > MAX_CAPTURE_SKEW_SECONDS:
        raise ValidationError(
            {
                "captured_at": (
                    "The photo must be taken with the camera just before "
                    "uploading. Please take a new photo."
                )
            }
        )

    taken_at = _exif_taken_at(file_obj)
    reference = captured_at if offline else now

    if taken_at is not None and abs((reference - taken_at).total_seconds()) > MAX_CAPTURE_SKEW_SECONDS:
        raise ValidationError(
            {"image": "This photo was not taken just now. Please use the camera."}
        )
