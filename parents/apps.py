from django.apps import AppConfig


class ParentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "parents"
    verbose_name = "Parents"

    def ready(self):
        import parents.signals  # noqa: F401
