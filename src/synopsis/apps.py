from django.apps import AppConfig


class SynopsisConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "synopsis"

    def ready(self):
        # Ensure default groups exist at startup
        try:
            from .utils import ensure_global_groups

            ensure_global_groups()
        except Exception:
            # During migrations / checks, DB might not be ready; ignore
            pass
