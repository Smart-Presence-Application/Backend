"""School signals and signal receivers."""

from django.db import transaction
from django.db.models.signals import pre_save, post_delete
from django.dispatch import Signal, receiver

from common.emails import (
    send_account_created_email,
    send_account_deactivated_email,
)

from .models import School


school_activated = Signal()
school_deactivated = Signal()


@receiver(school_activated)
def on_school_activated(
    sender,
    school,
    password,
    **kwargs,
):
    send_account_created_email(
        sender=sender,
        user=school.admin,
        raw_password=password,
    )


@receiver(school_deactivated)
def on_school_deactivated(
    sender,
    school,
    **kwargs,
):
    send_account_deactivated_email(
        sender=sender,
        user=school.admin,
    )


@receiver(pre_save, sender=School)
def delete_old_logo_on_update(sender, instance, **kwargs):
    if not instance.pk:
        return

    try:
        old_logo = sender.objects.get(pk=instance.pk).logo
    except sender.DoesNotExist:
        return

    if old_logo and old_logo != instance.logo:
        transaction.on_commit(
            lambda: old_logo.delete(save=False)
        )
        

@receiver(post_delete, sender=School)
def delete_school_logo(sender, instance, **kwargs):
    logo = instance.logo

    if logo:
        transaction.on_commit(
            lambda: logo.delete(save=False)
        )