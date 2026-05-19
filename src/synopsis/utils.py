import hashlib
from datetime import timedelta

from django.contrib.auth.models import Group
from django.conf import settings
from django.utils import timezone

BRAND = "CE Synopsis"
DEFAULT_ADVISORY_INVITATION_MESSAGE = (
    "We would greatly value your expertise and feedback on this synopsis. "
    "Your input will help strengthen the final output for the wider "
    "conservation community."
)
DEFAULT_PROTOCOL_REVIEW_MESSAGE = (
    "Please review the protocol for this synopsis and provide any comments "
    "using the feedback link below."
)
DEFAULT_ACTION_LIST_REVIEW_MESSAGE = (
    "Please review the action list for this synopsis and provide any comments "
    "using the feedback link below."
)
DEFAULT_SYNOPSIS_REVIEW_MESSAGE = (
    "Please review the synopsis document and provide any comments using the "
    "feedback link below."
)


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
    if kind == "action_list_review":
        return f"[Action requested] Action list for review — {title}"
    if kind == "action_list_reminder":
        due = _format_due(due_date) if due_date else "soon"
        return f"[Reminder] Action list feedback due for {title} ({due})"
    if kind == "synopsis_review":
        return f"[Action requested] Synopsis for review — {title}"
    if kind == "synopsis_reminder":
        due = _format_due(due_date) if due_date else "soon"
        return f"[Reminder] Synopsis feedback due for {title} ({due})"
    return f"[{BRAND}] {title}"


def reply_to_list(user_email: str | None) -> list[str]:
    """Prefer the inviter's email, fall back to DEFAULT_FROM_EMAIL."""
    fallback = settings.DEFAULT_FROM_EMAIL
    return [user_email or fallback]


def default_advisory_invitation_message() -> str:
    return DEFAULT_ADVISORY_INVITATION_MESSAGE


def default_protocol_review_message() -> str:
    return DEFAULT_PROTOCOL_REVIEW_MESSAGE


def default_action_list_review_message() -> str:
    return DEFAULT_ACTION_LIST_REVIEW_MESSAGE


def default_synopsis_review_message() -> str:
    return DEFAULT_SYNOPSIS_REVIEW_MESSAGE


def advisory_member_display_name(member) -> str:
    if not member:
        return "advisory board member"
    name_parts = [
        getattr(member, "first_name", ""),
        getattr(member, "last_name", ""),
    ]
    name = " ".join(part.strip() for part in name_parts if part and part.strip())
    return name or getattr(member, "email", "") or "advisory board member"


def minimum_allowed_deadline_date():
    return timezone.localdate() + timedelta(days=1)


GLOBAL_GROUPS = ["manager", "author", "external_collaborator"]


def ensure_global_groups():
    for name in GLOBAL_GROUPS:
        Group.objects.get_or_create(name=name)


def reference_hash(*parts: str) -> str:
    """Return a stable sha1 fingerprint for deduplication."""

    normalised = "|".join((part or "").strip().lower() for part in parts)
    return hashlib.sha1(normalised.encode("utf-8", errors="ignore")).hexdigest()
