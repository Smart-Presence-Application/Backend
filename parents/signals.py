"""Parent signal receivers."""

import logging

from django.db.models.signals import pre_save
from django.dispatch import receiver

from accounts.models import User
from attendance_student.signals import attendance_finalized
from common.choices import UserRole

from .models import Parent
from .services import notify_attendance

logger = logging.getLogger(__name__)


@receiver(attendance_finalized)
def notify_parents_of_attendance(sender, session, record_ids=None, **kwargs):
    """
    Notify parents once attendance is final.

    Runs after the attendance commit; a failure here must not undo or break
    the teacher's lock, so it is logged instead of raised.
    """
    try:
        notify_attendance(session=session, record_ids=record_ids)
    except Exception:
        logger.exception("Parent notifications failed for session %s", session.pk)


@receiver(pre_save, sender=User)
def forget_initial_password_on_change(sender, instance, **kwargs):
    """
    Once a parent sets their own password, stop keeping the generated
    one readable for staff.
    """

    if (
        instance.pk is None
        or instance.role != UserRole.PARENT
        or getattr(instance, "_keep_initial_password", False)
    ):
        return

    old_password = (
        User.objects.filter(pk=instance.pk).values_list("password", flat=True).first()
    )

    if old_password is not None and old_password != instance.password:
        Parent.objects.filter(user_id=instance.pk).update(initial_password="")
