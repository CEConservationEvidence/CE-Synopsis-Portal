from django.contrib.auth.models import Group

GLOBAL_GROUPS = ["manager", "author", "external_collaborator"]


def ensure_global_groups():
    for name in GLOBAL_GROUPS:
        Group.objects.get_or_create(name=name)
