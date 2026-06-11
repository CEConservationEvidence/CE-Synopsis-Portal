"""Shared utility functions for permissions, email text, deadlines, and references."""

import hashlib
import html
import re
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


def advisory_privacy_settings() -> dict[str, str]:
    privacy = getattr(settings, "ADVISORY_PRIVACY", {}) or {}
    return {
        "controller_name": (
            (privacy.get("controller_name") or "").strip()
            or "Conservation Evidence"
        ),
        "lawful_basis": (
            (privacy.get("lawful_basis") or "").strip()
            or "legitimate interests in running the advisory review workflow"
        ),
        "retention_summary": (
            (privacy.get("retention_summary") or "").strip()
            or (
                "for the duration of the synopsis project and afterwards in line "
                "with the organisation's records retention policy"
            )
        ),
        "shared_with": (
            (privacy.get("shared_with") or "").strip()
            or "authorised project authors and managers"
        ),
        "ico_url": (
            (privacy.get("ico_url") or "").strip()
            or "https://ico.org.uk/make-a-complaint/"
        ),
    }


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


def normalize_project_action_names(raw) -> list[str]:
    if isinstance(raw, str):
        values = raw.splitlines()
    elif raw:
        values = raw
    else:
        values = []

    cleaned = []
    seen = set()
    for value in values:
        label = re.sub(r"\s+", " ", str(value or "")).strip()
        if not label:
            continue
        key = label.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return cleaned


def project_action_name_values(project, *, include_intervention_titles: bool = False) -> list[str]:
    values = normalize_project_action_names(
        getattr(project, "saved_action_names", "") if project else ""
    )
    if include_intervention_titles and project and getattr(project, "pk", None):
        from .models import SynopsisIntervention

        intervention_titles = SynopsisIntervention.objects.filter(
            subheading__chapter__project=project
        ).order_by(
            "subheading__chapter__position",
            "subheading__position",
            "position",
            "id",
        ).values_list("title", flat=True)
        values = normalize_project_action_names(list(values) + list(intervention_titles))
    return values


GLOBAL_GROUPS = ["manager", "author", "external_collaborator"]


def ensure_global_groups():
    for name in GLOBAL_GROUPS:
        Group.objects.get_or_create(name=name)


def is_external_author_user(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if getattr(user, "is_staff", False):
        return False
    return user.groups.filter(name="external_collaborator").exists()


def reference_hash(*parts: str) -> str:
    """Return a stable sha1 fingerprint for deduplication."""

    normalised = "|".join((part or "").strip().lower() for part in parts)
    return hashlib.sha1(normalised.encode("utf-8", errors="ignore")).hexdigest()


def _reference_canonical(reference):
    return reference.canonical if hasattr(reference, "canonical") else reference


def reference_summary_seed_citation(reference) -> str:
    canonical = _reference_canonical(reference)
    parts = []
    authors = (canonical.authors or "").strip()
    if authors:
        parts.append(authors)
    year = canonical.publication_year
    if year:
        parts.append(f"({year})")
    title = (canonical.title or "").strip()
    if title:
        parts.append(title)
    citation = " ".join(parts).strip()
    if len(citation) > 500:
        citation = citation[:497].rstrip() + "..."
    return citation


def reference_export_default_citation(reference) -> str:
    canonical = _reference_canonical(reference)

    def _clean(value):
        return (value or "").strip()

    def _doi_url(raw):
        value = _clean(raw)
        if not value:
            return ""
        lowered = value.lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/"):
            if lowered.startswith(prefix):
                value = value[len(prefix):]
                break
        if value.lower().startswith("doi:"):
            value = value[4:]
        value = value.strip()
        return f"https://doi.org/{value}" if value else ""

    parts = []
    authors = _clean(canonical.authors)
    year = canonical.publication_year
    if authors and year:
        parts.append(f"{authors} ({year})")
    elif authors:
        parts.append(authors)
    elif year:
        parts.append(f"({year})")

    title = _clean(canonical.title)
    if title:
        parts.append(f"{title.rstrip('.')}.")

    journal = _clean(canonical.journal)
    volume = _clean(canonical.volume)
    issue = _clean(canonical.issue)
    pages = _clean(canonical.pages)
    if journal or volume or issue or pages:
        source_bits = []
        if journal:
            source_bits.append(journal)
        vol_issue = ""
        if volume and issue:
            vol_issue = f"{volume}({issue})"
        elif volume:
            vol_issue = volume
        elif issue:
            vol_issue = f"({issue})"
        if vol_issue:
            source_bits.append(vol_issue)
        if pages:
            source_bits.append(pages)
        if source_bits:
            parts.append(", ".join(source_bits).rstrip(".") + ".")

    doi_url = _doi_url(canonical.doi)
    source_url = _clean(canonical.url)
    if doi_url:
        parts.append(doi_url)
    elif source_url:
        parts.append(source_url)

    return " ".join([part for part in parts if part]).strip()


def normalize_reference_summary_citation(value, reference) -> str:
    text = (value or "").strip()
    if not text:
        return ""
    if reference is None:
        return text
    inherited_values = {
        reference_summary_seed_citation(reference),
        reference_export_default_citation(reference),
    }
    return "" if text in inherited_values else text


def reference_summary_custom_citation(summary) -> str:
    if not summary or not getattr(summary, "reference", None):
        return (getattr(summary, "citation", "") or "").strip()
    return normalize_reference_summary_citation(summary.citation, summary.reference)


def reference_summary_effective_citation(summary) -> str:
    custom = reference_summary_custom_citation(summary)
    if custom:
        return custom
    if summary and getattr(summary, "reference", None):
        return reference_export_default_citation(
            summary.reference
        ) or reference_summary_seed_citation(summary.reference)
    return (getattr(summary, "citation", "") or "").strip()


_ITALIC_TAG_RE = re.compile(r"(?i)(</?(?:i|em)>)")


def split_inline_italic_markup(text: str) -> list[tuple[str, bool]]:
    """Split a text fragment into plain/italic segments using simple <i>/<em> tags."""

    raw_text = html.unescape(text or "")
    italic = False
    segments = []
    for part in _ITALIC_TAG_RE.split(raw_text):
        if not part:
            continue
        lowered = part.lower()
        if lowered in {"<i>", "<em>"}:
            italic = True
            continue
        if lowered in {"</i>", "</em>"}:
            italic = False
            continue
        segments.append((part, italic))
    return segments
