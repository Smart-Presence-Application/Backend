from pathlib import Path
from uuid import uuid4


def user_profile_image_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"users/profile_images/{instance.id}{extension}"


def school_logo_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"schools/logo/{instance.code}{extension}"


def std_profile_image_upload_path(instance, filename):
    extension = Path(filename).suffix.lower()
    return f"student/profile_images/{instance.id}{extension}"

def _teacher_attendance_image_path(instance, filename, kind):
    extension = Path(filename).suffix.lower()
    return (
        f"teacher_attendance/{instance.date:%Y/%m/%d}/"
        f"{instance.teacher_id}_{kind}_{uuid4().hex[:8]}{extension}"
    )


def teacher_check_in_image_upload_path(instance, filename):
    return _teacher_attendance_image_path(instance, filename, "in")


def teacher_check_out_image_upload_path(instance, filename):
    return _teacher_attendance_image_path(instance, filename, "out")


def notification_attachment_upload_path(instance, filename):
    name = Path(filename)
    stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.stem)[:80]
    return (
        f"notifications/{instance.notification_id}/"
        f"{uuid4().hex[:8]}_{stem or 'file'}{name.suffix.lower()}"
    )


def notification_attachment_storage():
    """
    Storage for notification attachments of any type.

    Cloudinary's image storage accepts images only, so with Cloudinary on,
    attachments (PDFs, videos, documents) go to its "raw" storage, which
    takes any file. Otherwise the default storage is used as is.
    """

    from django.conf import settings
    from django.core.files.storage import default_storage

    if not settings.USE_CLOUDINARY:
        return default_storage

    from cloudinary_storage.storage import RawMediaCloudinaryStorage

    return RawMediaCloudinaryStorage()
