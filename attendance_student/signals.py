"""
Keep AI face embeddings in step with student records.

An embedding is keyed by (school, student_id) and built from one
image, so it becomes stale whenever any of those three change, and
orphaned when the student is deleted. In each case the local
registration row is dropped immediately and the AI service is told to
delete the embedding once the transaction commits.

Code that replaces a profile image *because* it is registering that
image (see services.register_face_for_student) sets
``_skip_face_invalidation`` on the instance so the fresh registration
is not thrown away.

``attendance_finalized`` is sent after commit whenever attendance
becomes final: when a session is locked (``record_ids=None`` meaning
every record), and when an admin changes records of a locked session.
"""

from functools import partial

from django.db import transaction
from django.db.models.signals import pre_delete, pre_save
from django.dispatch import Signal, receiver

from students.models import Student

from . import ai_client
from .models import FaceRegistration

attendance_finalized = Signal()


def _schedule_ai_delete(*, school_id, student_id) -> None:
    transaction.on_commit(
        partial(
            ai_client.delete_face_quietly,
            school_id=school_id,
            student_id=student_id,
        )
    )


@receiver(pre_save, sender=Student)
def invalidate_face_on_student_change(sender, instance, **kwargs):
    if instance.pk is None or getattr(instance, "_skip_face_invalidation", False):
        return

    old = (
        Student.objects.filter(pk=instance.pk)
        .values("school_id", "student_id", "profile_image")
        .first()
    )

    if old is None:
        return

    image = instance.profile_image
    image_changed = (
        (image.name or "") != (old["profile_image"] or "")
        or (bool(image) and not getattr(image, "_committed", True))
    )
    identity_changed = (
        instance.school_id != old["school_id"]
        or (instance.student_id or "").strip().upper() != old["student_id"]
    )

    if not (image_changed or identity_changed):
        return

    deleted, _ = FaceRegistration.objects.filter(student_id=instance.pk).delete()

    if deleted:
        _schedule_ai_delete(
            school_id=old["school_id"],
            student_id=old["student_id"],
        )


@receiver(pre_delete, sender=Student)
def delete_face_on_student_delete(sender, instance, **kwargs):
    if FaceRegistration.objects.filter(student_id=instance.pk).exists():
        _schedule_ai_delete(
            school_id=instance.school_id,
            student_id=instance.student_id,
        )
