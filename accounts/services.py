"""Business logic for authentication workflows."""

import logging
from django.db import transaction
from rest_framework_simplejwt.exceptions import TokenError
from .models import User
from accounts.authentication import (
    blacklist,
    generate_pair,
    rotate_refresh,
)
from accounts.signals import account_deactivated

logger = logging.getLogger(__name__)


@transaction.atomic
def login_user(user) -> dict[str, object]:
    logger.info("User logged in: %s", user.email)

    return {
        "user": user,
        "tokens": generate_pair(user),
    }


def logout_user(refresh_token: str |None) -> None:
    try:
        blacklist(refresh_token)
    except TokenError:
        logger.warning(
            "Attempted logout with invalid refresh token.",
        )


def refresh_user_tokens(refresh_token: str | None) -> dict[str, str]:
    if not refresh_token:
        raise TokenError("Refresh token cookie is missing.")

    return rotate_refresh(refresh_token)


@transaction.atomic
def change_user_password(
    user,
    new_password: str,
    *,
    changed_by=None,
) -> None:
    user.set_password(new_password)
    user.save(update_fields=["password", "updated_at"])

    logger.info(
        "Password for %s was changed by %s",
        user.email,
        getattr(changed_by, "email", changed_by),
    )


@transaction.atomic
def set_user_status(
    user,
    is_active: bool,
    *,
    changed_by=None,
) -> bool:
    """
    Activate or deactivate a user account.

    Returns True if the status changed.
    """
    if user.is_active == is_active:
        return False

    user.is_active = is_active
    user.save(update_fields=["is_active", "updated_at"])

    logger.info(
        "User %s was %s by %s",
        user.email,
        "activated" if is_active else "deactivated",
        getattr(changed_by, "email", changed_by),
    )

    if not is_active:
        account_deactivated.send(
            sender=user.__class__,
            user=user,
            changed_by=changed_by,
        )

    return True


@transaction.atomic
def update_user_details(
    *,
    user: User,
    validated_data: dict,
) -> User:
    if not validated_data:
        return user

    for field, value in validated_data.items():
        setattr(user, field, value)

    user.save(update_fields=[*validated_data.keys(), "updated_at"])
    return user


@transaction.atomic
def update_user_profile_image(
    *,
    user: User,
    image,
) -> User:
    user.profile_image = image
    user.save(update_fields=["profile_image", "updated_at"])
    return user