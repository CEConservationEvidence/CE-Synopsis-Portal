from django.apps import apps
from django.db.models.signals import post_migrate
from django.dispatch import receiver

from .utils import ensure_global_groups


@receiver(post_migrate)
def synopsis_post_migrate(sender, app_config, **kwargs):
    if app_config.name != "synopsis":
        return
    auth_group = apps.get_model("auth", "Group")
    if auth_group is None:
        return
    ensure_global_groups()
