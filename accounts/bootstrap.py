"""Bootstrap routines executed when the server starts."""

import logging

from django.conf import settings

logger = logging.getLogger(__name__)


def create_default_superuser() -> None:
    """
    Ensure a superuser exists, using the credentials from the environment.

    Does nothing when the credentials are missing, the email already exists,
    or the database is not ready yet. The user is built without the manager
    so the "account created" email is not sent on every server start.
    """
    email = getattr(settings, "SUPERUSER_EMAIL", "")
    password = getattr(settings, "SUPERUSER_PASSWORD", "")

    if not email or not password:
        logger.info(
            "Skipping default superuser creation: "
            "SUPERUSER_EMAIL/SUPERUSER_PASSWORD not configured."
        )
        return

    from django.db import DatabaseError
    from django.db.utils import OperationalError, ProgrammingError

    from accounts.models import User
    from common.choices import UserRole

    name = getattr(settings, "SUPERUSER_NAME", "") or "Smart Presence Admin"

    try:
        if User.objects.filter(email__iexact=email).exists():
            return

        user = User(
            email=User.objects.normalize_email(email),
            name=name,
            role=UserRole.SUPER_ADMIN,
            is_active=True,
            is_staff=True,
            is_superuser=True,
        )
        user.set_password(password)
        user.save()
    except (OperationalError, ProgrammingError):
        logger.warning(
            "Skipping default superuser creation: database is not ready."
        )
    except DatabaseError:
        logger.exception("Failed to create the default superuser.")
    else:
        logger.info("Created default superuser %s.", user.email)
