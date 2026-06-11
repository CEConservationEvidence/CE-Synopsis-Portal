"""Template context helpers shared across synopsis pages."""

from .models import UserRole
from .utils import advisory_privacy_settings, is_external_author_user


ROLE_LABELS = dict(UserRole.ROLE_CHOICES)
ROLE_PRIORITY = [
    "manager",
    "author",
    "advisory_board",
    "external_collaborator",
]


def _preferred_role_label(user, request):
    if not getattr(user, "is_authenticated", False):
        return ""

    group_names = set(user.groups.values_list("name", flat=True))
    if getattr(user, "is_superuser", False):
        return "System admin"
    if getattr(user, "is_staff", False) or "manager" in group_names:
        return "Manager"
    if "external_collaborator" in group_names:
        return "External Author"

    resolver_match = getattr(request, "resolver_match", None)
    project_id = getattr(resolver_match, "kwargs", {}).get("project_id")
    role_qs = UserRole.objects.filter(user=user)

    if project_id is not None:
        current_roles = set(
            role_qs.filter(project_id=project_id).values_list("role", flat=True)
        )
        for role_key in ROLE_PRIORITY:
            if role_key in current_roles:
                return ROLE_LABELS.get(role_key, role_key.replace("_", " ").title())

    if "author" in group_names:
        return "Author"

    known_roles = set(role_qs.values_list("role", flat=True))
    for role_key in ROLE_PRIORITY:
        if role_key in known_roles:
            return ROLE_LABELS.get(role_key, role_key.replace("_", " ").title())
    return ""


def _user_display_name(user):
    if not getattr(user, "is_authenticated", False):
        return ""
    full_name = user.get_full_name().strip()
    return full_name or user.username or getattr(user, "email", "") or "Signed-in user"


def navigation_roles(request):
    user = getattr(request, "user", None)
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    is_external_author = is_external_author_user(user)
    return {
        "nav_is_external_author": is_external_author,
        "nav_can_manage_library": is_authenticated and not is_external_author,
        "nav_can_create_project": is_authenticated and not is_external_author,
        "nav_user_display_name": _user_display_name(user),
        "nav_user_role_label": _preferred_role_label(user, request),
        "advisory_privacy": advisory_privacy_settings(),
    }
