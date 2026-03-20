from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .utils import ensure_global_groups


@receiver(post_migrate)
def synopsis_post_migrate(sender, app_config, **kwargs):
    if app_config.name != "synopsis":
        return
    ensure_global_groups()
