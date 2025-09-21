import hashlib

from django.contrib.auth.models import Group
from django.conf import settings
from django.utils import timezone

BRAND = "CE Synopsis"


def email_subject(kind: str, project, due_date=None) -> str:
    """Return a contextual subject for outbound emails.

    kind: one of 'invite', 'invite_reminder', 'protocol_review'
    """
    title = project.title if project else ""
    def _format_due(dt_value, with_label=False):
        if not dt_value:
            return None
        if hasattr(dt_value, "tzinfo"):
            try:
                aware = timezone.localtime(dt_value)
            except (ValueError, TypeError):
                aware = dt_value
            formatted = aware.strftime("%d %b %Y %H:%M")
        else:
            formatted = dt_value.strftime("%d %b %Y")
        return f"{formatted}" if not with_label else f"reply by {formatted}"

    if kind == "invite":
        due = f" ({_format_due(due_date, with_label=True)})" if due_date else ""
        return f"[{BRAND}] Invitation to advise on {title}{due}"
    if kind == "invite_reminder":
        due = _format_due(due_date) if due_date else "soon"
        return f"[Reminder] {title} — please reply by {due}"
    if kind == "protocol_review":
        return f"[Action requested] Protocol for review — {title}"
    if kind == "protocol_reminder":
        due = _format_due(due_date) if due_date else "soon"
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


def reference_hash(*parts: str) -> str:
    """Return a stable sha1 fingerprint for deduplication."""

    normalised = "|".join((part or "").strip().lower() for part in parts)
    return hashlib.sha1(normalised.encode("utf-8", errors="ignore")).hexdigest()
