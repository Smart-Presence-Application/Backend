import os
import sys

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Account Management"

    def ready(self):
        import accounts.signals  # noqa: F401

        if self._should_bootstrap_superuser():
            from accounts.bootstrap import create_default_superuser

            create_default_superuser()

    @staticmethod
    def _should_bootstrap_superuser() -> bool:
        """
        True only on a real server start, never for management commands.

        Under runserver only the autoreloader's child (RUN_MAIN set) runs it,
        so it happens once. WSGI/ASGI servers have no command name at all.
        """
        management_command = sys.argv[1] if len(sys.argv) > 1 else ""

        if management_command == "runserver":
            return os.environ.get("RUN_MAIN") == "true"

        return management_command == ""
