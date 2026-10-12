"""Bootstrap routines executed after `migrate` (see AccountsConfig)."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def create_default_superuser(using: str = "default"):
    """
    Ensure a superuser exists, using the credentials from the environment.

    Returns the created user, or None when the credentials are missing, the
    email already exists, or the database is not ready yet. The user is built
    without the manager so the "account created" email is not sent.
    """
    email = getattr(settings, "SUPERUSER_EMAIL", "")
    password = getattr(settings, "SUPERUSER_PASSWORD", "")

    if not email or not password:
        logger.info(
            "Skipping default superuser creation: "
            "SUPERUSER_EMAIL/SUPERUSER_PASSWORD not configured."
        )
        return None

    from django.db import DatabaseError
    from django.db.utils import OperationalError, ProgrammingError

    from accounts.models import User
    from common.choices import UserRole

    name = getattr(settings, "SUPERUSER_NAME", "") or "Smart Presence Admin"

    try:
        if User.objects.using(using).filter(email__iexact=email).exists():
            return None

        user = User(
            email=User.objects.normalize_email(email),
            name=name,
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save(using=using)
    except (OperationalError, ProgrammingError):
        logger.warning(
            "Skipping default superuser creation: database is not ready."
        )
        return None
    except DatabaseError:
        logger.exception("Failed to create the default superuser.")
        return None

    logger.info("Created default superuser %s.", user.email)
    return user
