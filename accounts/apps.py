from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "accounts"
    verbose_name = "Account Management"

    def ready(self):
        import accounts.signals  # noqa: F401

        post_migrate.connect(
            _bootstrap_superuser,
            sender=self,
            dispatch_uid="accounts.bootstrap_superuser",
        )


def _bootstrap_superuser(sender, using="default", verbosity=1, **kwargs):
    """
    Create the default superuser after `migrate`.

    post_migrate fires on every `migrate` run (even with nothing to apply),
    so `pip install -r requirements.txt && python manage.py migrate` is
    enough to provision the account on a fresh deploy.
    """
    from accounts.bootstrap import create_default_superuser

    user = create_default_superuser(using=using)

    if user is not None and verbosity >= 1:
        print(f"  Created default superuser {user.email}.")
