"""
Read and switch maintenance mode, cached briefly so every request stays
cheap. Each process caches the flag for ``CACHE_SECONDS``, so a switch
reaches every worker within that time.
"""

from django.core.cache import cache
from django.db import DatabaseError

from .models import MaintenanceSettings

CACHE_KEY = "system:maintenance"
CACHE_SECONDS = 5


def get_settings() -> MaintenanceSettings:
    settings_row, _ = MaintenanceSettings.objects.get_or_create(pk=1)
    return settings_row


def maintenance_state() -> dict:
    """
    ``{"enabled": bool, "message": str}``. Never raises: if the table is
    missing (before migrating) maintenance counts as off.
    """

    state = cache.get(CACHE_KEY)

    if state is None:
        try:
            row = get_settings()
            state = {"enabled": row.is_enabled, "message": row.display_message}
        except DatabaseError:
            return {"enabled": False, "message": ""}

        cache.set(CACHE_KEY, state, CACHE_SECONDS)

    return state


def set_maintenance(*, actor, is_enabled: bool | None = None, message: str | None = None) -> MaintenanceSettings:
    row = get_settings()

    if is_enabled is not None:
        row.is_enabled = is_enabled

    if message is not None:
        row.message = message.strip()

    row.updated_by = actor
    row.save()
    cache.delete(CACHE_KEY)

    return row
