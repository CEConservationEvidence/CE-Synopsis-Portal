from .utils import is_external_author_user


def navigation_roles(request):
    user = getattr(request, "user", None)
    is_authenticated = bool(getattr(user, "is_authenticated", False))
    is_external_author = is_external_author_user(user)
    return {
        "nav_is_external_author": is_external_author,
        "nav_can_manage_library": is_authenticated and not is_external_author,
        "nav_can_create_project": is_authenticated and not is_external_author,
    }
