"""Account signals and signal receivers."""

import logging

from django.dispatch import Signal, receiver
from django.db.models.signals import pre_save, post_delete
from accounts.models import User

from common.emails import (
    send_account_created_email,
    send_account_deactivated_email,
)

logger = logging.getLogger(__name__)


user_created = Signal()
account_deactivated = Signal()


@receiver(user_created)
def created_email(sender, user, raw_password=None, **kwargs):
    send_account_created_email(
        sender=sender,
        user=user,
        raw_password=raw_password,
        **kwargs,
    )


@receiver(account_deactivated)
def account_deactivated_email(sender, user, changed_by=None, **kwargs):
    send_account_deactivated_email(
        sender=sender,
        user=user,
        changed_by=changed_by,
        **kwargs,
    )
    
    
@receiver(pre_save, sender=User)
def delete_old_profile_image(sender, instance: User, **kwargs) -> None:
    """Delete the previous profile image when a new one is uploaded."""
    if not instance.pk:
        return

    try:
        old_instance = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        return

    if (
        old_instance.profile_image
        and old_instance.profile_image != instance.profile_image
    ):
        old_instance.profile_image.delete(save=False)


@receiver(post_delete, sender=User)
def delete_profile_image(sender, instance: User, **kwargs) -> None:
    """Delete the profile image when the user is deleted."""
    if instance.profile_image:
        instance.profile_image.delete(save=False)