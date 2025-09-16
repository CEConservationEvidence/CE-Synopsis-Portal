from django.contrib.auth.models import Group
from django.conf import settings

BRAND = "CE Synopsis"


def email_subject(kind: str, project, due_date=None) -> str:
    """Return a contextual subject for outbound emails.

    kind: one of 'invite', 'invite_reminder', 'protocol_review'
    """
    title = project.title if project else ""
    if kind == "invite":
        due = f" (reply by {due_date.strftime('%d %b %Y')})" if due_date else ""
        return f"[{BRAND}] Invitation to advise on {title}{due}"
    if kind == "invite_reminder":
        due = due_date.strftime("%d %b %Y") if due_date else "soon"
        return f"[Reminder] {title} — please reply by {due}"
    if kind == "protocol_review":
        return f"[Action requested] Protocol for review — {title}"
    if kind == "protocol_reminder":
        due = due_date.strftime("%d %b %Y") if due_date else "soon"
        return f"[Reminder] Protocol feedback due for {title} ({due})"
    return f"[{BRAND}] {title}"


def reply_to_list(user_email: str | None) -> list[str]:
    """Prefer the inviter's email, fall back to DEFAULT_FROM_EMAIL."""
    fallback = settings.DEFAULT_FROM_EMAIL
    return [user_email or fallback]


GLOBAL_GROUPS = ["manager", "author", "external_collaborator"]


def ensure_global_groups():
    for name in GLOBAL_GROUPS:
        Group.objects.get_or_create(name=name)
