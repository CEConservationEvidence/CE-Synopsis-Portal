from django.apps import AppConfig


class SynopsisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "synopsis"

    def ready(self):
        from . import signals  # noqa: F401
