import datetime as dt
import hashlib
import json
import logging
import os
import re
import uuid
from decimal import Decimal
from urllib.parse import urlparse, urlencode

import jwt
import requests
import rispy

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, send_mail
from django.db import connection, transaction
from collections import defaultdict

from django.db.models import Count, Max
from django.http import (
    HttpResponseBadRequest,
    Http404,
    JsonResponse,
    HttpResponseNotAllowed,
)
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.safestring import mark_safe
from django import forms
from django.views.decorators.csrf import csrf_exempt

from .forms import (
    ProtocolUpdateForm,
    ActionListUpdateForm,
    CreateUserForm,
    AdvisoryBoardMemberForm,
    AdvisoryInviteForm,
    AssignAuthorsForm,
    FunderForm,
    ProjectDeleteForm,
    ProjectSettingsForm,
    AdvisoryBulkInviteForm,
    ProtocolSendForm,
    ActionListSendForm,
    ReminderScheduleForm,
    ProtocolReminderScheduleForm,
    ActionListReminderScheduleForm,
    ParticipationConfirmForm,
    ParticipationDeclineForm,
    ProtocolFeedbackForm,
    ActionListFeedbackForm,
    ProtocolFeedbackCloseForm,
    ActionListFeedbackCloseForm,
    ReferenceBatchUploadForm,
    ReferenceScreeningForm,
    CollaborativeUpdateForm,
    AdvisoryCustomFieldForm,
    AdvisoryCustomFieldPlacementForm,
    AdvisoryMemberCustomDataForm,
)
from .models import (
    Project,
    Protocol,
    ActionList,
    AdvisoryBoardMember,
    AdvisoryBoardInvitation,
    AdvisoryBoardCustomField,
    AdvisoryBoardCustomFieldValue,
    AdvisoryBoardCustomFieldValueHistory,
    Funder,
    UserRole,
    ProjectPhaseEvent,
    ProjectChangeLog,
    ProtocolFeedback,
    ActionListFeedback,
    ReferenceSourceBatch,
    ReferenceSourceBatchNoteHistory,
    Reference,
    ProtocolRevision,
    ActionListRevision,
    CollaborativeSession,
)
from .utils import ensure_global_groups, email_subject, reply_to_list, reference_hash


ONLYOFFICE_SETTINGS = getattr(settings, "ONLYOFFICE", {})

logger = logging.getLogger(__name__)


_COLLAB_INVITE_TABLE_EXISTS = None


def _collaborative_invitation_table_ready():
    global _COLLAB_INVITE_TABLE_EXISTS
    if _COLLAB_INVITE_TABLE_EXISTS is not None:
        return _COLLAB_INVITE_TABLE_EXISTS

    table_name = CollaborativeSession.invitations.through._meta.db_table
    try:
        tables = connection.introspection.table_names()
    except Exception as exc:  # pragma: no cover - defensive guard
        logger.warning(
            "Could not inspect database tables for collaborative invites: %s", exc
        )
        _COLLAB_INVITE_TABLE_EXISTS = False
        return False

    _COLLAB_INVITE_TABLE_EXISTS = table_name in tables
    return _COLLAB_INVITE_TABLE_EXISTS


def _onlyoffice_enabled() -> bool:
    return bool(ONLYOFFICE_SETTINGS.get("base_url"))


def _user_is_manager(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True
    return user.groups.filter(name="manager").exists()


def _user_can_edit_project(user, project) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if _user_is_manager(user):
        return True
    try:
        return project.author_users.filter(id=user.id).exists()
    except Exception:
        return False


def _member_section_key(member: AdvisoryBoardMember) -> str:
    response = (member.response or "").upper()
    if response == "Y":
        return AdvisoryBoardCustomField.SECTION_ACCEPTED
    if response == "N":
        return AdvisoryBoardCustomField.SECTION_DECLINED
    return AdvisoryBoardCustomField.SECTION_PENDING


def _localise_datetime(value):
    if not value:
        return None
    if isinstance(value, dt.datetime):
        try:
            return timezone.localtime(value)
        except (ValueError, TypeError, OverflowError):
            return value
    return value


def _status_badge(label, value, badge, *, date=None, date_label=None, note=None):
    payload = {
        "label": label,
        "value": value,
        "badge": badge,
    }
    if date:
        payload["date"] = _localise_datetime(date)
    if date_label:
        payload["date_label"] = date_label
    if note:
        payload["note"] = note
    return payload


def _member_glance_statuses(member: AdvisoryBoardMember) -> list[dict]:
    statuses: list[dict] = []

    if getattr(member, "invite_sent", False):
        statuses.append(
            _status_badge(
                "Invite",
                "Sent",
                "success",
                date=getattr(member, "invite_sent_at", None),
                date_label="Sent",
            )
        )
    else:
        statuses.append(
            _status_badge(
                "Invite",
                "Draft",
                "secondary",
                note="No invite sent yet",
            )
        )

    response = (getattr(member, "response", "") or "").upper()
    if response == "Y":
        note = None
        if getattr(member, "participation_confirmed", False):
            note = "Participation confirmed"
        elif not getattr(member, "participation_confirmed", False):
            note = "Confirmation pending"
        statuses.append(
            _status_badge(
                "Response",
                "Accepted",
                "success",
                date=getattr(member, "response_date", None),
                date_label="Responded",
                note=note,
            )
        )
    elif response == "N":
        statuses.append(
            _status_badge(
                "Response",
                "Declined",
                "danger",
                date=getattr(member, "response_date", None),
                date_label="Responded",
            )
        )
    else:
        statuses.append(
            _status_badge(
                "Response",
                "Pending",
                "warning",
                note="Awaiting response",
            )
        )

    latest_action_feedback = getattr(member, "latest_action_list_feedback_obj", None)
    if latest_action_feedback and getattr(latest_action_feedback, "submitted_at", None):
        statuses.append(
            _status_badge(
                "Action list",
                "Feedback received",
                "success",
                date=latest_action_feedback.submitted_at,
                date_label="Received",
            )
        )
    elif response == "N":
        statuses.append(
            _status_badge(
                "Action list",
                "Not applicable",
                "secondary",
                note="Member declined",
            )
        )
    elif getattr(member, "sent_action_list_at", None):
        if getattr(member, "feedback_on_action_list_deadline", None):
            if getattr(member, "action_list_reminder_sent", False):
                statuses.append(
                    _status_badge(
                        "Action list",
                        "Reminder sent",
                        "info",
                        date=getattr(member, "action_list_reminder_sent_at", None),
                        date_label="Reminded",
                    )
                )
            else:
                statuses.append(
                    _status_badge(
                        "Action list",
                        "Awaiting feedback",
                        "warning",
                        date=getattr(member, "feedback_on_action_list_deadline", None),
                        date_label="Due",
                    )
                )
        else:
            statuses.append(
                _status_badge(
                    "Action list",
                    "Sent",
                    "primary",
                    date=getattr(member, "sent_action_list_at", None),
                    date_label="Sent",
                )
            )
    else:
        statuses.append(
            _status_badge(
                "Action list",
                "Not sent",
                "secondary",
            )
        )

    protocol_feedback_received = getattr(member, "feedback_on_protocol_received", None)
    if protocol_feedback_received:
        statuses.append(
            _status_badge(
                "Protocol",
                "Feedback received",
                "success",
                date=protocol_feedback_received,
                date_label="Received",
            )
        )
    elif response == "N":
        statuses.append(
            _status_badge(
                "Protocol",
                "Not applicable",
                "secondary",
                note="Member declined",
            )
        )
    elif getattr(member, "sent_protocol_at", None):
        if getattr(member, "feedback_on_protocol_deadline", None):
            if getattr(member, "protocol_reminder_sent", False):
                statuses.append(
                    _status_badge(
                        "Protocol",
                        "Reminder sent",
                        "info",
                        date=getattr(member, "protocol_reminder_sent_at", None),
                        date_label="Reminded",
                    )
                )
            else:
                statuses.append(
                    _status_badge(
                        "Protocol",
                        "Awaiting feedback",
                        "warning",
                        date=getattr(member, "feedback_on_protocol_deadline", None),
                        date_label="Due",
                    )
                )
        else:
            statuses.append(
                _status_badge(
                    "Protocol",
                    "Sent",
                    "primary",
                    date=getattr(member, "sent_protocol_at", None),
                    date_label="Sent",
                )
            )
    else:
        statuses.append(
            _status_badge(
                "Protocol",
                "Not sent",
                "secondary",
            )
        )

    return statuses


def _user_can_force_end_session(user, project, session) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if _user_is_manager(user):
        return True

    owner_id = session.started_by_id
    user_id = getattr(user, "pk", None)

    if owner_id is None:
        return _user_can_edit_project(user, project)

    if user_id is None:
        return False

    return str(owner_id) == str(user_id)


def _log_project_change(project, user, action: str, details: str = ""):
    changed_by = user if getattr(user, "is_authenticated", False) else None
    ProjectChangeLog.objects.create(
        project=project, changed_by=changed_by, action=action, details=details
    )


def _format_value(value):
    if value in (None, ""):
        return "—"
    if isinstance(value, dt.date):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _user_display(user: User) -> str:
    full = user.get_full_name()
    return full or user.username


def _advisory_member_display(member: AdvisoryBoardMember) -> str:
    if not member:
        return "Advisory board member"
    parts = [member.first_name.strip() if member.first_name else ""]
    if member.last_name:
        parts.append(member.last_name.strip())
    name = " ".join(part for part in parts if part).strip()
    if not name:
        name = member.email or "Advisory board member"
    return name


def _funder_contact_label(first: str | None, last: str | None) -> str:
    parts = [
        part.strip() for part in [first or "", last or ""] if part and part.strip()
    ]
    return " ".join(parts) if parts else "—"


def _format_deadline(deadline):
    if not deadline:
        return "—"
    try:
        aware = timezone.localtime(deadline)
    except (ValueError, TypeError):
        aware = deadline
    return aware.strftime("%d %b %Y %H:%M")


def _format_file_size(size_bytes):
    try:
        size = int(size_bytes)
    except (TypeError, ValueError):
        return "—"
    if size < 0:
        return "—"
    units = ["B", "KB", "MB", "GB", "TB"]
    for unit in units:
        if size < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{size} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024


def _apply_revision_to_protocol(protocol, revision) -> tuple[str, str]:
    try:
        with revision.file.open("rb") as source:
            content = source.read()
    except FileNotFoundError:
        raise FileNotFoundError("Revision file missing")

    if not content:
        raise ValueError("Revision file empty")

    base_name = revision.original_name or os.path.basename(revision.file.name)
    new_filename = f"protocols/{uuid.uuid4()}_{base_name}"
    protocol.document.save(new_filename, ContentFile(content), save=False)
    protocol.current_revision = revision
    protocol.save(update_fields=["document", "current_revision"])
    return base_name, _format_file_size(revision.file_size)


def _apply_revision_to_action_list(action_list, revision) -> tuple[str, str]:
    try:
        with revision.file.open("rb") as source:
            content = source.read()
    except FileNotFoundError:
        raise FileNotFoundError("Revision file missing")

    if not content:
        raise ValueError("Revision file empty")

    base_name = revision.original_name or os.path.basename(revision.file.name)
    new_filename = f"action_lists/{uuid.uuid4()}_{base_name}"
    action_list.document.save(new_filename, ContentFile(content), save=False)
    action_list.current_revision = revision
    action_list.save(update_fields=["document", "current_revision"])
    return base_name, _format_file_size(revision.file_size)


COLLAB_SESSION_DURATION = CollaborativeSession.DEFAULT_DURATION


def _normalize_document_type(document_type: str) -> str | None:
    mapping = {
        "protocol": CollaborativeSession.DOCUMENT_PROTOCOL,
        "protocols": CollaborativeSession.DOCUMENT_PROTOCOL,
        "action-list": CollaborativeSession.DOCUMENT_ACTION_LIST,
        "action_list": CollaborativeSession.DOCUMENT_ACTION_LIST,
        "actionlist": CollaborativeSession.DOCUMENT_ACTION_LIST,
    }
    return mapping.get((document_type or "").lower())


def _get_document_for_type(project, document_type):
    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL:
        return getattr(project, "protocol", None)
    if document_type == CollaborativeSession.DOCUMENT_ACTION_LIST:
        return getattr(project, "action_list", None)
    return None


def _get_active_collaborative_session(project, document_type):
    session = (
        CollaborativeSession.objects.filter(
            project=project,
            document_type=document_type,
            is_active=True,
        )
        .order_by("-started_at", "-id")
        .first()
    )
    if session and session.has_expired():
        session.is_active = False
        session.save(update_fields=["is_active"])
        return None
    return session


def _end_active_collaborative_session(
    project, document_type, *, ended_by=None, reason=""
):
    session = _get_active_collaborative_session(project, document_type)
    if not session:
        return None
    session.mark_inactive(
        ended_by=ended_by,
        reason=reason or f"{_document_label(document_type)} collaborative editing closed",
    )
    return session


def _ensure_collaborative_invite_link(
    request,
    project,
    document_type,
    invitation=None,
    *,
    member=None,
    feedback=None,
):
    if not _onlyoffice_enabled():
        return ""

    document = _get_document_for_type(project, document_type)
    if not _document_requires_file(document):
        return ""

    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL and getattr(
        document, "feedback_closed_at", None
    ):
        _end_active_collaborative_session(
            project,
            document_type,
            ended_by=getattr(request, "user", None),
            reason="Protocol feedback window closed",
        )
        return ""

    if document_type == CollaborativeSession.DOCUMENT_ACTION_LIST and getattr(
        document, "feedback_closed_at", None
    ):
        _end_active_collaborative_session(
            project,
            document_type,
            ended_by=getattr(request, "user", None),
            reason="Action list feedback window closed",
        )
        return ""

    session = _get_active_collaborative_session(project, document_type)
    created = False

    if not session:
        initial_revision = getattr(document, "current_revision", None)
        if not initial_revision and hasattr(document, "latest_revision"):
            try:
                initial_revision = document.latest_revision()
            except Exception:
                initial_revision = None

        session_kwargs = {
            "project": project,
            "document_type": document_type,
            "started_by": (
                request.user
                if getattr(request.user, "is_authenticated", False)
                else None
            ),
            "last_activity_at": timezone.now(),
        }

        if document_type == CollaborativeSession.DOCUMENT_PROTOCOL:
            session_kwargs["initial_protocol_revision"] = initial_revision
        else:
            session_kwargs["initial_action_list_revision"] = initial_revision

        session = CollaborativeSession.objects.create(**session_kwargs)
        created = True

    if invitation and session:
        if _collaborative_invitation_table_ready():
            session.invitations.add(invitation)
        else:
            logger.warning(
                "Collaborative invite join table missing; skipping association for session %s",
                session.pk,
            )

    if created:
        _log_project_change(
            project,
            request.user,
            f"{_document_label(document_type)} collaborative editing started",
            f"Session {session.token} shared with advisory invite {invitation.email if invitation else ''}".strip(),
        )

    params = {}
    if member:
        params["member"] = str(member.id)
    if feedback:
        params["feedback"] = str(feedback.token)

    slug = _document_type_slug(document_type)
    path = reverse(
        "synopsis:collaborative_edit", args=[project.id, slug, session.token]
    )
    if params:
        path = f"{path}?{urlencode(params)}"
    return request.build_absolute_uri(path)


def _document_detail_url(project_id, document_type):
    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL:
        return reverse("synopsis:protocol_detail", args=[project_id])
    return reverse("synopsis:action_list_detail", args=[project_id])


def _document_label(document_type):
    return (
        "Protocol"
        if document_type == CollaborativeSession.DOCUMENT_PROTOCOL
        else "Action list"
    )


def _document_type_slug(document_type):
    return (
        "protocol"
        if document_type == CollaborativeSession.DOCUMENT_PROTOCOL
        else "action-list"
    )


def _collaborative_session_or_404(project, document_type, token):
    return get_object_or_404(
        CollaborativeSession,
        project=project,
        document_type=document_type,
        token=token,
    )


def _document_requires_file(document) -> bool:
    return bool(document and getattr(document, "document", None))


def _onlyoffice_editor_js_url() -> str:
    base = ONLYOFFICE_SETTINGS.get("base_url", "").rstrip("/")
    if not base:
        return ""
    return f"{base}/web-apps/apps/api/documents/api.js"


def _document_filetype(file_name: str) -> str:
    ext = (os.path.splitext(file_name)[1] or "").lstrip(".").lower()
    return ext or "docx"


def _build_onlyoffice_config(
    request,
    project,
    document,
    session,
    document_type,
    participant=None,
):
    document_file = getattr(document, "document", None)
    if not document_file:
        raise ValueError("Document has no file attached")

    file_url = request.build_absolute_uri(document_file.url)
    file_type = _document_filetype(document_file.name)
    title = os.path.basename(document_file.name) or _document_label(document_type)
    doc_key = f"{project.id}-{document_type}-{session.id}-{int(session.started_at.timestamp())}"[
        -128:
    ]

    user = request.user
    user_id = str(getattr(user, "id", "anonymous"))
    user_name = (
        _user_display(user) if getattr(user, "is_authenticated", False) else "Anonymous"
    )
    user_email = (
        getattr(user, "email", "") if getattr(user, "is_authenticated", False) else ""
    )

    if participant:
        user_id = participant.get("id", user_id)
        user_name = participant.get("name", user_name)
        user_email = participant.get("email", user_email)

    callback_url = request.build_absolute_uri(
        reverse(
            "synopsis:collaborative_edit_callback",
            args=[project.id, _document_type_slug(document_type), session.token],
        )
    )

    config = {
        "document": {
            "fileType": file_type,
            "key": doc_key,
            "title": title,
            "url": file_url,
            "permissions": {
                "edit": True,
                "download": True,
                "print": True,
                "review": True,
            },
        },
        "editorConfig": {
            "callbackUrl": callback_url,
            "user": {
                "id": user_id,
                "name": user_name,
            },
            "mode": "edit",
            "customization": {
                "autosave": True,
                "forcesave": True,
            },
        },
    }

    if user_email:
        config["editorConfig"]["user"]["email"] = user_email

    secret = ONLYOFFICE_SETTINGS.get("jwt_secret")
    if secret:
        token = jwt.encode(config, secret, algorithm="HS256")
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        config["token"] = token

    return config


def _download_onlyoffice_file(file_url: str) -> bytes:
    raw_entries = [ONLYOFFICE_SETTINGS.get("base_url", "")]
    extra = ONLYOFFICE_SETTINGS.get("trusted_download_urls") or []
    if isinstance(extra, (list, tuple)):
        raw_entries.extend(extra)
    else:
        raw_entries.append(extra)

    allowed: list[tuple[str, str, int, str]] = []
    for entry in raw_entries:
        if not entry:
            continue
        try:
            parsed_allowed = urlparse(entry)
        except ValueError:
            continue
        if (
            parsed_allowed.scheme not in {"http", "https"}
            or not parsed_allowed.hostname
        ):
            continue
        allowed.append(
            (
                parsed_allowed.scheme,
                parsed_allowed.hostname.lower(),
                parsed_allowed.port
                or (443 if parsed_allowed.scheme == "https" else 80),
                (parsed_allowed.path or "/").rstrip("/"),
            )
        )

    try:
        parsed = urlparse(file_url)
    except ValueError:
        parsed = None

    if not parsed or parsed.scheme not in {"http", "https"} or not parsed.hostname:
        logger.warning("Blocked OnlyOffice download from invalid URL: %s", file_url)
        raise ValueError("Untrusted OnlyOffice download URL")

    candidate_host = parsed.hostname.lower()
    candidate_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    candidate_path = parsed.path or "/"

    matched = False
    for scheme, host, port, path_prefix in allowed:
        if scheme != parsed.scheme:
            continue
        if candidate_host != host or candidate_port != port:
            continue
        if path_prefix and path_prefix != "/":
            if candidate_path == path_prefix or candidate_path.startswith(
                f"{path_prefix}/"
            ):
                matched = True
                break
        else:
            matched = True
            break

    if not matched:
        logger.warning("Blocked OnlyOffice download from untrusted URL: %s", file_url)
        raise ValueError("Untrusted OnlyOffice download URL")

    timeout = ONLYOFFICE_SETTINGS.get("callback_timeout", 10)
    response = requests.get(file_url, timeout=timeout)
    response.raise_for_status()
    return response.content


def _onlyoffice_secret() -> str:
    return ONLYOFFICE_SETTINGS.get("jwt_secret", "")


def _extract_onlyoffice_token(request, payload: dict) -> str | None:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return payload.get("token") if isinstance(payload, dict) else None


def _parse_onlyoffice_callback(request) -> dict:
    try:
        body = request.body.decode("utf-8") or "{}"
    except UnicodeDecodeError as exc:
        logger.warning("OnlyOffice callback body decode failed: %s", exc)
        raise ValueError("Invalid payload encoding")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        logger.warning("OnlyOffice callback payload JSON error: %s", exc)
        raise ValueError("Invalid JSON payload")

    secret = _onlyoffice_secret()
    if not secret:
        return payload

    token = _extract_onlyoffice_token(request, payload)
    if not token:
        logger.warning("OnlyOffice callback missing JWT token")
        raise PermissionDenied("Missing callback token")

    try:
        decoded = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.InvalidTokenError as exc:
        logger.warning("OnlyOffice callback token invalid: %s", exc)
        raise PermissionDenied("Invalid callback token")

    if not isinstance(decoded, dict):
        logger.warning("OnlyOffice callback token did not decode to a JSON object")
        raise PermissionDenied("Invalid callback payload")

    return decoded


def _create_protocol_feedback(project, member=None, email=None, invitation=None):
    proto = getattr(project, "protocol", None)
    kwargs = {
        "project": project,
        "member": member,
        "email": email or (member.email if member else ""),
        "invitation": invitation,
    }
    deadline = None
    if member:
        if member.response == "Y" and member.feedback_on_protocol_deadline:
            deadline = member.feedback_on_protocol_deadline
    elif invitation and invitation.due_date:
        combined = dt.datetime.combine(invitation.due_date, dt.time(23, 59))
        deadline = (
            timezone.make_aware(combined) if timezone.is_naive(combined) else combined
        )
    if proto:
        kwargs.update(
            {
                "protocol_document_name": getattr(proto.document, "name", ""),
                "protocol_document_last_updated": proto.last_updated,
                "protocol_stage_snapshot": proto.stage,
            }
        )
    kwargs["feedback_deadline_at"] = deadline
    return ProtocolFeedback.objects.create(**kwargs)


def _create_action_list_feedback(project, member=None, email=None, invitation=None):
    action_list = getattr(project, "action_list", None)
    kwargs = {
        "project": project,
        "action_list": action_list,
        "member": member,
        "email": email or (member.email if member else ""),
        "invitation": invitation,
    }
    deadline = None
    if member:
        if member.response == "Y" and member.feedback_on_action_list_deadline:
            deadline = member.feedback_on_action_list_deadline
    elif invitation and invitation.due_date:
        combined = dt.datetime.combine(invitation.due_date, dt.time(23, 59))
        deadline = (
            timezone.make_aware(combined) if timezone.is_naive(combined) else combined
        )
    if action_list:
        kwargs.update(
            {
                "action_list_document_name": getattr(action_list.document, "name", ""),
                "action_list_document_last_updated": action_list.last_updated,
                "action_list_stage_snapshot": action_list.stage,
            }
        )
    kwargs["feedback_deadline_at"] = deadline
    return ActionListFeedback.objects.create(**kwargs)


def _extract_reference_field(record: dict, key: str) -> str:
    value = record.get(key)
    if isinstance(value, list):
        if not value:
            return ""
        value = value[0]
    return value or ""


def _coerce_year(value) -> int | None:
    if isinstance(value, list):
        value = value[0] if value else None
    try:
        text = str(value).strip()
    except Exception:  # pragma: no cover - defensive
        return None
    if not text:
        return None
    for token in (text, text[:4]):
        try:
            return int(token)
        except (ValueError, TypeError):
            continue
    return None


def _combine_pages(record: dict) -> str:
    pages = _extract_reference_field(record, "pages")
    if pages:
        return pages
    start = _extract_reference_field(record, "start_page")
    end = _extract_reference_field(record, "end_page")
    if start and end:
        return f"{start}-{end}".strip("-")
    return start or end or ""


PLAIN_REFERENCE_SPLIT_RE = re.compile(r"\n\s*\n+")
PLAIN_REFERENCE_CITATION_RE = re.compile(
    r"""^(?P<authors>.+?)\s*\((?P<year>\d{4})\)\.\s*(?P<body>.+)$""",
    re.UNICODE,
)
PLAIN_REFERENCE_JOURNAL_RE = re.compile(
    r"^(?P<journal>[^\d:]+?)\s+(?P<volume>\d+)(?:\((?P<issue>[^)]+)\))?\s*:?\s*(?P<pages>[\d\-–]+)?\.?(?:\s|$)",
    re.UNICODE,
)
PLAIN_REFERENCE_DOI_RE = re.compile(r"doi[:\s]+(?P<doi>\S+)", re.IGNORECASE)
PLAIN_REFERENCE_URL_RE = re.compile(r"(https?://\S+)", re.IGNORECASE)


def _parse_plaintext_references(payload: str) -> list[dict]:
    """
    Parse a plain-text reference list.

    Each reference is expected to be separated by at least one blank line.
    The first non-empty line should contain the citation in the form:
        Authors (Year). "Title." Journal Volume(Issue): pages.
    Any subsequent non-empty lines are treated as the abstract.
    """

    if not payload or not payload.strip():
        return []

    entries = [
        block.strip()
        for block in PLAIN_REFERENCE_SPLIT_RE.split(payload.strip())
        if block.strip()
    ]
    parsed: list[dict] = []

    for chunk in entries:
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue

        citation = lines[0]
        abstract = " ".join(lines[1:]).strip()

        match = PLAIN_REFERENCE_CITATION_RE.match(citation)
        if not match:
            # If parsing fails we skip this chunk rather than guess.
            continue

        authors_part = match.group("authors").strip()
        year = (match.group("year") or "").strip()
        body = (match.group("body") or "").strip()

        title = ""
        remainder = ""

        if body.startswith('"'):
            closing_quote = body.find('"', 1)
            if closing_quote != -1:
                title = body[1:closing_quote].strip()
                remainder = body[closing_quote + 1 :].lstrip(" .")
            else:
                title = body.strip('" ')
        else:
            if ". " in body:
                title_part, remainder_part = body.split(". ", 1)
                title = title_part.strip()
                remainder = remainder_part.strip()
            else:
                dot_index = body.find(".")
                if dot_index != -1:
                    title = body[:dot_index].strip()
                    remainder = body[dot_index + 1 :].lstrip(" .")
                else:
                    title = body.strip()

        if not title:
            title = citation.strip()
        remainder = remainder.lstrip(" .")

        journal = volume = issue = pages = doi = url = ""

        if remainder:
            journal_match = PLAIN_REFERENCE_JOURNAL_RE.match(remainder)
            if journal_match:
                journal = (journal_match.group("journal") or "").strip(" .,;")
                volume = (journal_match.group("volume") or "").strip()
                issue = (journal_match.group("issue") or "").strip()
                pages = (journal_match.group("pages") or "").strip()

            doi_match = PLAIN_REFERENCE_DOI_RE.search(remainder)
            if doi_match:
                doi = doi_match.group("doi").rstrip(".,")

            url_match = PLAIN_REFERENCE_URL_RE.search(remainder)
            if url_match:
                url = url_match.group(1).rstrip(".,)")

        # If DOI or URL appear in the abstract/content include them.
        if not doi:
            doi_match = PLAIN_REFERENCE_DOI_RE.search(abstract)
            if doi_match:
                doi = doi_match.group("doi").rstrip(".,")
        if not url:
            url_match = PLAIN_REFERENCE_URL_RE.search(abstract)
            if url_match:
                url = url_match.group(1).rstrip(".,)")

        # Authors may be separated by semicolons or " and ".
        authors_tokens = []
        for token in re.split(r";|\band\b", authors_part, flags=re.IGNORECASE):
            cleaned = token.strip().strip(".;")
            if cleaned:
                authors_tokens.append(cleaned)

        parsed.append(
            {
                "primary_title": title,
                "title": title,
                "abstract": abstract,
                "authors": authors_tokens or [authors_part],
                "year": year,
                "publication_year": year,
                "journal_name": journal,
                "secondary_title": journal,
                "volume": volume,
                "issue": issue,
                "pages": pages,
                "doi": doi,
                "url": url,
            }
        )

    return parsed


def _advisory_board_context(
    project,
    *,
    user=None,
    member_form=None,
    reminder_form=None,
    protocol_form=None,
    feedback_close_form=None,
    action_list_form=None,
    action_list_feedback_close_form=None,
    custom_field_form=None,
):
    members_qs = project.advisory_board_members.prefetch_related(
        "protocol_feedback"
    ).order_by("last_name", "first_name")
    accepted_members = list(members_qs.filter(response="Y"))
    declined_members = list(members_qs.filter(response="N"))
    pending_members = list(members_qs.exclude(response__in=["Y", "N"]))

    for collection in (accepted_members, declined_members, pending_members):
        for member in collection:
            member.latest_feedback = member.latest_protocol_feedback
            latest_action_feedback = member.latest_action_list_feedback
            member.latest_action_list_feedback_obj = latest_action_feedback
            if (
                latest_action_feedback
                and not member.feedback_on_actions_received
                and (
                    latest_action_feedback.content
                    or latest_action_feedback.uploaded_document
                    or latest_action_feedback.submitted_at
                )
            ):
                member.feedback_on_actions_received = True

    all_members = accepted_members + pending_members + declined_members
    declined_with_reason = [
        member
        for member in declined_members
        if (member.participation_statement or "").strip()
    ]

    custom_fields = list(
        AdvisoryBoardCustomField.objects.filter(project=project).order_by(
            "display_order", "name", "id"
        )
    )
    fields_by_section = {
        key: [f for f in custom_fields if f.applies_to(key)]
        for key, _ in AdvisoryBoardCustomField.SECTION_CHOICES
    }
    grouped_fields_by_section = {
        key: AdvisoryBoardCustomField.group_fields_by_display(fields_by_section.get(key, []))
        for key, _ in AdvisoryBoardCustomField.SECTION_CHOICES
    }
    values_map = {
        (val.member_id, val.field_id): val.value
        for val in AdvisoryBoardCustomFieldValue.objects.filter(
            member__in=all_members, field__project=project
        )
    }

    for member in all_members:
        section_key = _member_section_key(member)
        member.section_key = section_key
        member.is_declined = (
            section_key == AdvisoryBoardCustomField.SECTION_DECLINED
        )
        section_fields = fields_by_section.get(section_key, [])
        member.custom_fields = section_fields
        member.has_custom_fields = bool(section_fields)
        member.custom_display_pairs = []
        member.custom_field_values = {}
        for field in section_fields:
            raw_value = values_map.get((member.id, field.id))
            formatted = field.format_value(raw_value)
            display_value = formatted if formatted not in (None, "") else "—"
            member.custom_display_pairs.append((field, display_value))
            member.custom_field_values[field.id] = display_value
        member.glance_statuses = _member_glance_statuses(member)

    direct_invites = project.invitations.filter(member__isnull=True).order_by(
        "-created_at"
    )

    not_invited_members = project.advisory_board_members.filter(invite_sent=False)
    pending_reminder_dates = [
        d
        for d in not_invited_members.filter(response_date__isnull=False)
        .order_by("response_date")
        .values_list("response_date", flat=True)
    ]
    if reminder_form is None:
        reminder_initial = {}
        if pending_reminder_dates:
            reminder_initial["reminder_date"] = pending_reminder_dates[0]
        reminder_form = ReminderScheduleForm(initial=reminder_initial)

    protocol_members = project.advisory_board_members.filter(
        sent_protocol_at__isnull=False,
        response="Y",
    )
    protocol_pending_dates = [
        d
        for d in protocol_members.filter(feedback_on_protocol_deadline__isnull=False)
        .order_by("feedback_on_protocol_deadline")
        .values_list("feedback_on_protocol_deadline", flat=True)
    ]
    if protocol_form is None:
        protocol_initial = {}
        if protocol_pending_dates:
            first_deadline = protocol_pending_dates[0]
            try:
                protocol_initial["deadline"] = timezone.localtime(first_deadline)
            except (ValueError, TypeError):
                protocol_initial["deadline"] = first_deadline
        protocol_form = ProtocolReminderScheduleForm(initial=protocol_initial)

    if member_form is None:
        member_form = AdvisoryBoardMemberForm()

    if custom_field_form is None:
        custom_field_form = AdvisoryCustomFieldForm(project)

    protocol_obj = getattr(project, "protocol", None)
    protocol_document_ready = bool(protocol_obj and getattr(protocol_obj, "document", None))
    if feedback_close_form is None:
        initial_close = {}
        if protocol_obj and protocol_obj.feedback_closure_message:
            initial_close["message"] = protocol_obj.feedback_closure_message
        feedback_close_form = ProtocolFeedbackCloseForm(initial=initial_close)
    protocol_feedback_state = {
        "protocol": protocol_obj,
        "is_closed": bool(getattr(protocol_obj, "feedback_closed_at", None)),
        "closed_at": getattr(protocol_obj, "feedback_closed_at", None),
        "closure_message": getattr(protocol_obj, "feedback_closure_message", ""),
        "deadline": protocol_pending_dates[0] if protocol_pending_dates else None,
        "document_ready": protocol_document_ready,
    }

    action_list_obj = getattr(project, "action_list", None)
    action_list_document_ready = bool(
        action_list_obj and getattr(action_list_obj, "document", None)
    )
    action_list_members = project.advisory_board_members.filter(
        sent_action_list_at__isnull=False,
        response="Y",
    )
    action_list_pending_dates = [
        d
        for d in action_list_members.filter(
            feedback_on_action_list_deadline__isnull=False
        )
        .order_by("feedback_on_action_list_deadline")
        .values_list("feedback_on_action_list_deadline", flat=True)
    ]
    if action_list_form is None:
        action_initial = {}
        if action_list_pending_dates:
            first_deadline = action_list_pending_dates[0]
            try:
                action_initial["deadline"] = timezone.localtime(first_deadline)
            except (ValueError, TypeError):
                action_initial["deadline"] = first_deadline
        action_list_form = ActionListReminderScheduleForm(initial=action_initial)

    if action_list_feedback_close_form is None:
        action_close_initial = {}
        if action_list_obj and action_list_obj.feedback_closure_message:
            action_close_initial["message"] = action_list_obj.feedback_closure_message
        action_list_feedback_close_form = ActionListFeedbackCloseForm(
            initial=action_close_initial
        )
    action_list_feedback_state = {
        "action_list": action_list_obj,
        "is_closed": bool(getattr(action_list_obj, "feedback_closed_at", None)),
        "closed_at": getattr(action_list_obj, "feedback_closed_at", None),
        "closure_message": getattr(action_list_obj, "feedback_closure_message", ""),
        "deadline": action_list_pending_dates[0] if action_list_pending_dates else None,
        "document_ready": action_list_document_ready,
    }

    section_palette = {
        AdvisoryBoardCustomField.SECTION_ACCEPTED: {
            "title": "Accepted members",
            "empty": "No accepted members yet.",
            "card": "border-start border-4 border-success",
            "header": "bg-success text-white",
        },
        AdvisoryBoardCustomField.SECTION_PENDING: {
            "title": "Pending members",
            "empty": "No pending members yet.",
            "card": "border-start border-4 border-warning",
            "header": "bg-warning",
        },
        AdvisoryBoardCustomField.SECTION_DECLINED: {
            "title": "Declined members",
            "empty": "No declined members yet.",
            "card": "border-start border-4 border-secondary",
            "header": "bg-secondary text-white",
        },
    }

    member_sections = [
        {
            "key": AdvisoryBoardCustomField.SECTION_ACCEPTED,
            "title": section_palette[AdvisoryBoardCustomField.SECTION_ACCEPTED][
                "title"
            ],
            "members": accepted_members,
            "empty_text": section_palette[AdvisoryBoardCustomField.SECTION_ACCEPTED][
                "empty"
            ],
            "card_class": section_palette[AdvisoryBoardCustomField.SECTION_ACCEPTED][
                "card"
            ],
            "header_class": section_palette[AdvisoryBoardCustomField.SECTION_ACCEPTED][
                "header"
            ],
            "fields": fields_by_section.get(
                AdvisoryBoardCustomField.SECTION_ACCEPTED, []
            ),
            "fields_by_group": grouped_fields_by_section.get(
                AdvisoryBoardCustomField.SECTION_ACCEPTED,
                AdvisoryBoardCustomField.group_fields_by_display([]),
            ),
        },
        {
            "key": AdvisoryBoardCustomField.SECTION_PENDING,
            "title": section_palette[AdvisoryBoardCustomField.SECTION_PENDING]["title"],
            "members": pending_members,
            "empty_text": section_palette[AdvisoryBoardCustomField.SECTION_PENDING][
                "empty"
            ],
            "card_class": section_palette[AdvisoryBoardCustomField.SECTION_PENDING][
                "card"
            ],
            "header_class": section_palette[AdvisoryBoardCustomField.SECTION_PENDING][
                "header"
            ],
            "fields": fields_by_section.get(
                AdvisoryBoardCustomField.SECTION_PENDING, []
            ),
            "fields_by_group": grouped_fields_by_section.get(
                AdvisoryBoardCustomField.SECTION_PENDING,
                AdvisoryBoardCustomField.group_fields_by_display([]),
            ),
        },
        {
            "key": AdvisoryBoardCustomField.SECTION_DECLINED,
            "title": section_palette[AdvisoryBoardCustomField.SECTION_DECLINED][
                "title"
            ],
            "members": declined_members,
            "empty_text": section_palette[AdvisoryBoardCustomField.SECTION_DECLINED][
                "empty"
            ],
            "card_class": section_palette[AdvisoryBoardCustomField.SECTION_DECLINED][
                "card"
            ],
            "header_class": section_palette[AdvisoryBoardCustomField.SECTION_DECLINED][
                "header"
            ],
            "fields": fields_by_section.get(
                AdvisoryBoardCustomField.SECTION_DECLINED, []
            ),
            "fields_by_group": grouped_fields_by_section.get(
                AdvisoryBoardCustomField.SECTION_DECLINED,
                AdvisoryBoardCustomField.group_fields_by_display([]),
            ),
        },
    ]
    for section in member_sections:
        section["has_fields"] = bool(section["fields"])

    group_names = [
        "personal",
        "invitation",
        "action",
        "protocol",
        "synopsis",
        "custom",
    ]
    combined_fields_by_group = {name: [] for name in group_names}
    seen_field_ids = {name: set() for name in group_names}

    for section in member_sections:
        field_ids_by_group = {}
        for group_name in group_names:
            group_fields = section["fields_by_group"].get(group_name, [])
            field_ids = [field.id for field in group_fields]
            field_ids_by_group[group_name] = field_ids
            for field in group_fields:
                if field.id not in seen_field_ids[group_name]:
                    combined_fields_by_group[group_name].append(field)
                    seen_field_ids[group_name].add(field.id)
        section["field_ids_by_group"] = field_ids_by_group

    def safe_count(members):
        count_attr = getattr(members, "count", None)
        if callable(count_attr):
            try:
                return count_attr()
            except TypeError:
                pass
        return len(members)

    total_member_count = (
        safe_count(accepted_members)
        + safe_count(pending_members)
        + safe_count(declined_members)
    )

    can_edit_members = _user_can_edit_project(user, project) if user else False

    status_badges = {
        AdvisoryBoardCustomField.SECTION_ACCEPTED: {
            "label": "Accepted",
            "badge_class": "text-bg-success",
            "row_class": "ab-row-status-accepted",
        },
        AdvisoryBoardCustomField.SECTION_PENDING: {
            "label": "Pending",
            "badge_class": "text-bg-warning",
            "row_class": "ab-row-status-pending",
        },
        AdvisoryBoardCustomField.SECTION_DECLINED: {
            "label": "Declined",
            "badge_class": "text-bg-danger",
            "row_class": "ab-row-status-declined",
        },
    }

    return {
        "project": project,
        "accepted_members": accepted_members,
        "declined_members": declined_members,
        "pending_members": pending_members,
        "member_sections": member_sections,
        "combined_fields_by_group": combined_fields_by_group,
        "member_status_badges": status_badges,
        "total_member_count": total_member_count,
        "section_fields": fields_by_section,
        "custom_fields": custom_fields,
        "custom_field_form": custom_field_form,
        "direct_invites": direct_invites,
        "form": member_form,
        "reminder_form": reminder_form,
        "pending_reminders": not_invited_members.count(),
        "pending_reminder_dates": pending_reminder_dates,
        "initial_reminder_log": project.change_log.filter(action="Scheduled reminders")
        .order_by("created_at")
        .first(),
        "protocol_reminder_form": protocol_form,
        "protocol_pending_count": protocol_members.count(),
        "protocol_pending_dates": protocol_pending_dates,
        "initial_protocol_reminder_log": project.change_log.filter(
            action="Scheduled protocol reminders"
        )
        .order_by("created_at")
        .first(),
        "protocol_feedback_state": protocol_feedback_state,
        "protocol_feedback_close_form": feedback_close_form,
        "action_list_reminder_form": action_list_form,
        "action_list_pending_count": action_list_members.count(),
        "action_list_pending_dates": action_list_pending_dates,
        "initial_action_list_reminder_log": project.change_log.filter(
            action="Scheduled action list reminders"
        )
        .order_by("created_at")
        .first(),
        "can_edit_members": can_edit_members,
        "action_list_feedback_state": action_list_feedback_state,
        "action_list_feedback_close_form": action_list_feedback_close_form,
        "section_palette": section_palette,
        "custom_field_group_choices": AdvisoryBoardCustomField.DISPLAY_GROUP_CHOICES,
        "declined_members_with_reason": declined_with_reason,
    }


# ---------------- Dashboard & Project Hub ----------------


@login_required
def dashboard(request):
    base_qs = Project.objects.prefetch_related("userrole_set__user").order_by(
        "-created_at"
    )
    completed_statuses = ["completed", "archived"]
    active_projects = list(base_qs.exclude(status__in=completed_statuses))
    completed_projects = list(base_qs.filter(status__in=completed_statuses))

    for proj in active_projects + completed_projects:
        proj.author_list = [
            role.user for role in proj.userrole_set.all() if role.role == "author"
        ]
    return render(
        request,
        "synopsis/dashboard.html",
        {
            "active_projects": active_projects,
            "completed_projects": completed_projects,
            "can_manage_projects": _user_is_manager(request.user),
        },
    )


class ProjectCreateForm(forms.ModelForm):
    start_date = forms.DateField(
        required=False,
        initial=timezone.localdate,
        widget=forms.DateInput(
            attrs={
                "type": "date",
                "class": "form-control bg-light text-muted",
                "readonly": "readonly",
                "tabindex": "-1",
            }
        ),
        disabled=True,
    )

    class Meta:
        model = Project
        fields = ["title", "start_date"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["start_date"].initial = timezone.localdate()


@login_required
def project_create(request):
    today = timezone.localdate()
    if request.method == "POST":
        pform = ProjectCreateForm(request.POST)
        aform = AssignAuthorsForm(request.POST)
        fform = FunderForm(request.POST)
        if pform.is_valid() and aform.is_valid() and fform.is_valid():
            if request.POST.get("edit") == "1":
                pform.fields["start_date"].initial = today
                return render(
                    request,
                    "synopsis/project_create.html",
                    {
                        "form": pform,
                        "authors_form": aform,
                        "funder_form": fform,
                    },
                )

            if request.POST.get("confirm") == "1":
                project = pform.save(commit=False)
                project.start_date = today
                project.save()

                _log_project_change(
                    project,
                    request.user,
                    "Project created",
                    f"Title: {project.title}; Start date: {_format_value(project.start_date)}",
                )

                authors = aform.cleaned_data.get("authors") or []
                for user in authors:
                    UserRole.objects.get_or_create(
                        user=user, project=project, role="author"
                    )
                if authors:
                    author_labels = ", ".join(_user_display(user) for user in authors)
                    _log_project_change(
                        project,
                        request.user,
                        "Assigned authors",
                        f"Initial author list: {author_labels}",
                    )

                if fform.has_meaningful_input():
                    funder = fform.save(commit=False)
                    funder.project = project
                    funder.name = Funder.build_display_name(
                        funder.organisation,
                        funder.contact_title,
                        funder.contact_first_name,
                        funder.contact_last_name,
                    )
                    funder.save()
                    contact_label = _funder_contact_label(
                        funder.contact_first_name, funder.contact_last_name
                    )
                    details = (
                        f"Organisation: {_format_value(funder.organisation)}; "
                        f"Title: {_format_value(funder.contact_title)}; "
                        f"Contact: {contact_label}; "
                        f"Funds allocated: {_format_value(funder.funds_allocated)}; "
                        f"Dates: {_format_value(funder.fund_start_date)} to {_format_value(funder.fund_end_date)}"
                    )
                    _log_project_change(project, request.user, "Added funder", details)

                messages.success(request, "Project created.")
                return redirect("synopsis:project_hub", project_id=project.id)

            hidden_project_form = ProjectCreateForm(request.POST)
            for field in hidden_project_form.fields.values():
                field.widget = forms.HiddenInput()
                field.disabled = False
            hidden_authors_form = AssignAuthorsForm(request.POST)
            hidden_authors_form.fields["authors"].widget = forms.MultipleHiddenInput()

            hidden_funder_form = FunderForm(request.POST)
            for name, field in hidden_funder_form.fields.items():
                field.widget = forms.HiddenInput()

            authors = aform.cleaned_data.get("authors") or []
            author_names = [_user_display(user) for user in authors]

            funder_cleaned = fform.cleaned_data
            funder_summary = {
                "organisation": funder_cleaned.get("organisation"),
                "contact_title": funder_cleaned.get("contact_title"),
                "contact": _funder_contact_label(
                    funder_cleaned.get("contact_first_name"),
                    funder_cleaned.get("contact_last_name"),
                ),
                "funds_allocated": funder_cleaned.get("funds_allocated"),
                "fund_start_date": funder_cleaned.get("fund_start_date"),
                "fund_end_date": funder_cleaned.get("fund_end_date"),
                "has_details": fform.has_meaningful_input(),
            }

            return render(
                request,
                "synopsis/project_create_confirm.html",
                {
                    "project_form": hidden_project_form,
                    "authors_form_hidden": hidden_authors_form,
                    "funder_form_hidden": hidden_funder_form,
                    "summary": {
                        "title": pform.cleaned_data["title"],
                        "start_date": today,
                        "authors": author_names,
                        "funder": funder_summary,
                    },
                },
            )
    else:
        pform = ProjectCreateForm(initial={"start_date": today})
        aform = AssignAuthorsForm()
        fform = FunderForm()

    return render(
        request,
        "synopsis/project_create.html",
        {"form": pform, "authors_form": aform, "funder_form": fform},
    )


@login_required
def project_hub(request, project_id):
    project = get_object_or_404(
        Project.objects.prefetch_related(
            "funders",
            "userrole_set__user",
            "change_log__changed_by",
            "phase_events",
        ),
        pk=project_id,
    )
    protocol = getattr(project, "protocol", None)
    action_list = getattr(project, "action_list", None)
    can_manage = _user_is_manager(request.user)

    funders = list(project.funders.all())
    funders.sort(
        key=lambda f: (
            f.fund_start_date or dt.date.max,
            (
                f.organisation or f.contact_last_name or f.contact_first_name or ""
            ).lower(),
        )
    )
    funding_values = [
        f.funds_allocated for f in funders if f.funds_allocated is not None
    ]
    total_funding = sum(funding_values, Decimal("0")) if funding_values else None
    start_dates = [f.fund_start_date for f in funders if f.fund_start_date]
    end_dates = [f.fund_end_date for f in funders if f.fund_end_date]
    funder_summary = {
        "count": len(funders),
        "total": total_funding,
        "earliest_start": min(start_dates) if start_dates else None,
        "latest_end": max(end_dates) if end_dates else None,
    }

    inv_qs = AdvisoryBoardInvitation.objects.filter(project=project)
    members_qs = AdvisoryBoardMember.objects.filter(project=project)
    ab_stats = {
        "members": members_qs.count(),
        "member_invites_sent": members_qs.filter(invite_sent=True).count(),
        "protocol_sent_to_members": members_qs.filter(
            sent_protocol_at__isnull=False
        ).count(),
        "invites_total": inv_qs.count(),
        "invites_member": inv_qs.filter(member__isnull=False).count(),
        "invites_direct": inv_qs.filter(member__isnull=True).count(),
        "accepted": inv_qs.filter(accepted=True).count(),
        "declined": inv_qs.filter(accepted=False).count(),
        "pending": inv_qs.filter(accepted__isnull=True).count(),
    }

    latest_batch = project.reference_batches.order_by("-created_at", "-id").first()
    reference_stats = {
        "batches": project.reference_batches.count(),
        "references": project.references.count(),
        "pending": project.references.filter(screening_status="pending").count(),
        "latest_batch": latest_batch,
    }

    phase_labels = dict(Project.PHASE_CHOICES)
    order = [k for k, _ in Project.PHASE_CHOICES]
    current_phase = project.phase
    try:
        idx = order.index(current_phase)
    except ValueError:
        idx = 0
    next_phase = order[idx + 1] if idx + 1 < len(order) else None
    last_event = project.phase_events.first()
    next_phase_label = phase_labels.get(next_phase) if next_phase else None

    change_log_entries = project.change_log.select_related("changed_by")[:10]

    return render(
        request,
        "synopsis/project_hub.html",
        {
            "project": project,
            "protocol": protocol,
            "action_list": action_list,
            "ab_stats": ab_stats,
            "reference_stats": reference_stats,
            "phase_labels": phase_labels,
            "next_phase": next_phase,
            "next_phase_label": next_phase_label,
            "last_phase_event": last_event,
            "authors": list(project.author_users),
            "change_log_entries": change_log_entries,
            "funders": funders,
            "funder_summary": funder_summary,
            "can_manage_project": _user_is_manager(request.user),
        },
    )


def _user_can_confirm_phase(user, project: Project) -> bool:
    if not user.is_authenticated:
        return False
    if user.is_staff:
        return True
    return UserRole.objects.filter(user=user, project=project, role="author").exists()


@login_required
def project_phase_confirm(request, project_id, phase):
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    if not _user_can_confirm_phase(request.user, project):
        messages.error(
            request,
            "You do not have permission to confirm milestones for this project.",
        )
        return redirect("synopsis:project_hub", project_id=project.id)

    valid_phases = [k for k, _ in Project.PHASE_CHOICES]
    if phase not in valid_phases:
        messages.error(request, "Invalid phase.")
        return redirect("synopsis:project_hub", project_id=project.id)

    order = valid_phases
    try:
        cur_idx = order.index(project.phase)
        tgt_idx = order.index(phase)
    except ValueError:
        messages.error(request, "Phase resolution error.")
        return redirect("synopsis:project_hub", project_id=project.id)

    if tgt_idx < cur_idx:
        messages.error(request, "Cannot move the phase backwards.")
        return redirect("synopsis:project_hub", project_id=project.id)

    project.phase_manual = phase
    project.phase_manual_updated = timezone.now()
    project.save(update_fields=["phase_manual", "phase_manual_updated"])

    note = (request.POST.get("note") or "").strip()
    ProjectPhaseEvent.objects.create(
        project=project, phase=phase, confirmed_by=request.user, note=note
    )

    messages.success(request, f"Phase confirmed: {dict(Project.PHASE_CHOICES)[phase]}")
    return redirect("synopsis:project_hub", project_id=project.id)


@login_required
def project_authors_manage(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _user_is_manager(request.user):
        messages.error(request, "Only managers can update authors for this project.")
        return redirect("synopsis:project_hub", project_id=project.id)

    current_authors_qs = project.author_users
    current_ids = set(current_authors_qs.values_list("id", flat=True))

    if request.method == "POST":
        form = AssignAuthorsForm(request.POST)
        if form.is_valid():
            new_authors = form.cleaned_data.get("authors") or User.objects.none()
            new_ids = set(new_authors.values_list("id", flat=True))
            added_ids = new_ids - current_ids
            removed_ids = current_ids - new_ids

            for user_id in added_ids:
                UserRole.objects.get_or_create(
                    user_id=user_id, project=project, role="author"
                )
            if removed_ids:
                UserRole.objects.filter(
                    project=project, role="author", user_id__in=removed_ids
                ).delete()

            if added_ids or removed_ids:
                added_names = ", ".join(
                    _user_display(user)
                    for user in User.objects.filter(id__in=added_ids)
                )
                removed_names = ", ".join(
                    _user_display(user)
                    for user in User.objects.filter(id__in=removed_ids)
                )
                fragments = []
                if added_names:
                    fragments.append(f"Added: {added_names}")
                if removed_names:
                    fragments.append(f"Removed: {removed_names}")
                _log_project_change(
                    project,
                    request.user,
                    "Updated authors",
                    "; ".join(fragments) or "No membership changes",
                )
                messages.success(request, "Author assignments updated.")
            else:
                messages.info(request, "No changes made to authors.")

            return redirect("synopsis:project_hub", project_id=project.id)
    else:
        form = AssignAuthorsForm(initial={"authors": current_authors_qs})

    return render(
        request,
        "synopsis/project_authors_form.html",
        {
            "project": project,
            "form": form,
            "current_authors": current_authors_qs,
        },
    )


@login_required
def project_funder_add(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _user_is_manager(request.user):
        messages.error(request, "Only managers can add funder information.")
        return redirect("synopsis:project_hub", project_id=project.id)

    instance = Funder(project=project)
    if request.method == "POST":
        form = FunderForm(request.POST, instance=instance)
        if form.is_valid():
            if not form.has_meaningful_input():
                form.add_error(None, "Enter details before saving a funder.")
            else:
                funder = form.save(commit=False)
                funder.project = project
                funder.name = Funder.build_display_name(
                    funder.organisation,
                    funder.contact_title,
                    funder.contact_first_name,
                    funder.contact_last_name,
                )
                funder.save()
                contact_label = _funder_contact_label(
                    funder.contact_first_name, funder.contact_last_name
                )
                details = (
                    f"Organisation: {_format_value(funder.organisation)}; "
                    f"Contact: {contact_label}; "
                    f"Title: {_format_value(funder.contact_title)}; "
                    f"Funds allocated: {_format_value(funder.funds_allocated)}; "
                    f"Start date: {_format_value(funder.fund_start_date)}; "
                    f"End date: {_format_value(funder.fund_end_date)}"
                )
                _log_project_change(project, request.user, "Added funder", details)
                messages.success(request, "Funder details added.")
                return redirect("synopsis:project_hub", project_id=project.id)
    else:
        form = FunderForm(instance=instance)

    return render(
        request,
        "synopsis/funder_form.html",
        {"project": project, "form": form, "funder": None, "mode": "add"},
    )


@login_required
def project_funder_edit(request, project_id, funder_id):
    project = get_object_or_404(Project, pk=project_id)
    funder = get_object_or_404(Funder, pk=funder_id, project=project)
    if not _user_is_manager(request.user):
        messages.error(request, "Only managers can edit funder information.")
        return redirect("synopsis:project_hub", project_id=project.id)

    if request.method == "POST":
        form = FunderForm(request.POST, instance=funder)
        if form.is_valid():
            if not form.has_meaningful_input():
                form.add_error(None, "Enter details before saving a funder.")
            else:
                old_values = {
                    field: getattr(funder, field)
                    for field in (
                        "organisation",
                        "contact_title",
                        "contact_first_name",
                        "contact_last_name",
                        "funds_allocated",
                        "fund_start_date",
                        "fund_end_date",
                    )
                }
                updated = form.save(commit=False)
                updated.project = project
                updated.name = Funder.build_display_name(
                    updated.organisation,
                    updated.contact_title,
                    updated.contact_first_name,
                    updated.contact_last_name,
                )
                updated.save()
                changes = []
                for field in (
                    "organisation",
                    "contact_title",
                    "funds_allocated",
                    "fund_start_date",
                    "fund_end_date",
                ):
                    old_value = old_values[field]
                    new_value = getattr(updated, field)
                    if old_value != new_value:
                        label = field.replace("_", " ").title()
                        changes.append(
                            f"{label}: {_format_value(old_value)} → {_format_value(new_value)}"
                        )
                old_contact = _funder_contact_label(
                    old_values["contact_first_name"], old_values["contact_last_name"]
                )
                new_contact = _funder_contact_label(
                    updated.contact_first_name, updated.contact_last_name
                )
                if old_contact != new_contact:
                    changes.append(f"Contact: {old_contact} → {new_contact}")
                detail_msg = (
                    "; ".join(changes) if changes else "No visible field changes"
                )
                _log_project_change(project, request.user, "Updated funder", detail_msg)
                messages.success(request, "Funder details updated.")
                return redirect("synopsis:project_hub", project_id=project.id)
    else:
        form = FunderForm(instance=funder)

    return render(
        request,
        "synopsis/funder_form.html",
        {"project": project, "form": form, "funder": funder, "mode": "edit"},
    )


@login_required
def project_funder_delete(request, project_id, funder_id):
    project = get_object_or_404(Project, pk=project_id)
    funder = get_object_or_404(Funder, pk=funder_id, project=project)
    if not _user_is_manager(request.user):
        messages.error(request, "Only managers can remove funders.")
        return redirect("synopsis:project_hub", project_id=project.id)

    if request.method == "POST":
        detail = "Removed funder " + Funder.build_display_name(
            funder.organisation,
            funder.contact_title,
            funder.contact_first_name,
            funder.contact_last_name,
        )
        funder.delete()
        _log_project_change(project, request.user, "Removed funder", detail)
        messages.success(request, "Funder removed.")
        return redirect("synopsis:project_hub", project_id=project.id)

    return render(
        request,
        "synopsis/funder_confirm_delete.html",
        {"project": project, "funder": funder},
    )


@login_required
def project_delete(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _user_is_manager(request.user):
        messages.error(request, "Only managers can delete projects.")
        return redirect("synopsis:project_hub", project_id=project.id)

    next_url = request.POST.get("next") or request.GET.get("next")
    cancel_url = next_url or reverse("synopsis:manager_dashboard")

    if request.method == "POST":
        form = ProjectDeleteForm(request.POST, project=project)
        if form.is_valid():
            title = project.title
            project.delete()
            messages.success(request, f"Project '{title}' deleted.")
            return redirect(next_url or "synopsis:manager_dashboard")
    else:
        form = ProjectDeleteForm(project=project)

    return render(
        request,
        "synopsis/project_confirm_delete.html",
        {
            "project": project,
            "form": form,
            "next_url": next_url,
            "cancel_url": cancel_url,
        },
    )


@login_required
def protocol_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    can_manage = _user_is_manager(request.user)
    can_edit_documents = _user_can_edit_project(request.user, project)
    protocol_history_queryset = (
        project.change_log.filter(action__icontains="protocol")
        .select_related("changed_by")
        .order_by("-created_at", "-id")
    )
    protocol_history_entries = []
    for log in protocol_history_queryset:
        segments = [
            segment.strip() for segment in log.details.split("|") if segment.strip()
        ]
        reason = ""
        changes = []
        for segment in segments:
            if segment.lower().startswith("reason:"):
                reason = segment.split(":", 1)[1].strip()
            else:
                changes.append(segment)
        protocol_history_entries.append(
            {
                "log": log,
                "changes": changes,
                "reason": reason,
                "actor": _user_display(log.changed_by) if log.changed_by else "System",
            }
        )

    revision_entries = []
    if protocol:
        revision_queryset = protocol.revisions.select_related("uploaded_by")
        for revision in revision_queryset:
            file_name = revision.original_name or os.path.basename(revision.file.name)
            try:
                download_url = revision.file.url
            except ValueError:
                download_url = ""
            revision_entries.append(
                {
                    "revision": revision,
                    "is_current": protocol.current_revision_id == revision.id,
                    "file_name": file_name,
                    "file_size": _format_file_size(revision.file_size),
                    "uploaded_by": (
                        _user_display(revision.uploaded_by)
                        if revision.uploaded_by
                        else "—"
                    ),
                    "download_url": download_url,
                    "can_mark_final": can_manage
                    and (
                        protocol.stage != "final"
                        or protocol.current_revision_id != revision.id
                    ),
                }
            )

    current_revision_entry = next(
        (entry for entry in revision_entries if entry["is_current"]), None
    )
    current_revision_download_url = ""
    if current_revision_entry:
        try:
            current_revision_download_url = current_revision_entry["revision"].file.url
        except ValueError:
            current_revision_download_url = ""

    protocol_document_ready = bool(protocol and getattr(protocol, "document", None))
    existing_file_name = protocol.document.name if protocol_document_ready else ""
    has_existing_file = bool(existing_file_name or revision_entries)
    first_upload_pending = not has_existing_file
    final_stage_locked = bool(
        protocol and protocol.stage == "final" and has_existing_file
    )

    collaborative_enabled = _onlyoffice_enabled()
    protocol_closed = bool(protocol and protocol.feedback_closed_at)
    collaborative_session = None
    collaborative_resume_url = ""
    collaborative_force_end_url = ""
    collaborative_slug = _document_type_slug(CollaborativeSession.DOCUMENT_PROTOCOL)
    if collaborative_enabled:
        collaborative_session = _get_active_collaborative_session(
            project, CollaborativeSession.DOCUMENT_PROTOCOL
        )
        if collaborative_session and protocol_closed:
            collaborative_session.mark_inactive(
                ended_by=request.user if request.user.is_authenticated else None,
                reason="Protocol feedback window closed",
            )
            collaborative_session = None
        if collaborative_session:
            collaborative_resume_url = reverse(
                "synopsis:collaborative_edit",
                args=[project.id, collaborative_slug, collaborative_session.token],
            )
            collaborative_force_end_url = reverse(
                "synopsis:collaborative_force_end",
                args=[project.id, collaborative_slug, collaborative_session.token],
            )
    if collaborative_session:
        collaborative_can_override = _user_can_force_end_session(
            request.user, project, collaborative_session
        )
    else:
        collaborative_can_override = False
    if protocol_closed:
        collaborative_enabled = False
        collaborative_session = None
        collaborative_resume_url = ""
        collaborative_force_end_url = ""
        collaborative_can_override = False

    if request.method == "POST":
        form = ProtocolUpdateForm(request.POST, request.FILES, instance=protocol)
        if form.is_valid():
            new_stage = form.cleaned_data.get("stage")
            uploaded_file = form.cleaned_data.get("document")
            reason = form.cleaned_data.get("change_reason", "")

            is_new_protocol = protocol is None
            stage_changed = bool(protocol) and protocol.stage != new_stage
            replacing_file = bool(uploaded_file)

            if final_stage_locked and new_stage == "final" and replacing_file:
                form.add_error(
                    "document",
                    "Finalized protocols cannot be replaced. Switch the stage back to Draft to revise the document.",
                )

            needs_reason = (not is_new_protocol) and (stage_changed or replacing_file)
            if needs_reason and not reason:
                form.add_error(
                    "change_reason",
                    "Please capture the reason for this revision so the team has context.",
                )

            if not form.errors:
                old_stage = protocol.stage if protocol else None
                old_file = (
                    protocol.document.name if protocol and protocol.document else None
                )

                revision_content = None
                revision_filename = ""
                if uploaded_file:
                    uploaded_file.seek(0)
                    revision_content = ContentFile(uploaded_file.read())
                    uploaded_file.seek(0)
                    revision_filename = os.path.basename(
                        uploaded_file.name or "protocol_upload"
                    )

                obj = form.save(commit=False)
                obj.project = project
                obj.save()
                form.save_m2m()

                protocol = obj

                new_file = obj.document.name if obj.document else None
                changes = []

                if is_new_protocol:
                    changes.append("Created protocol record")
                elif old_stage != obj.stage:
                    changes.append(
                        f"Stage: {_format_value(old_stage)} → {_format_value(obj.stage)}"
                    )

                if old_file != new_file:
                    if new_file and old_file:
                        changes.append(f"File replaced: {old_file} → {new_file}")
                    elif new_file:
                        changes.append(f"File uploaded: {new_file}")
                    elif old_file:
                        changes.append(f"File removed: {old_file}")

                revision_instance = None
                if revision_content is not None:
                    revision_instance = ProtocolRevision(
                        protocol=obj,
                        stage=obj.stage,
                        change_reason=(
                            reason
                            if reason
                            else ("Initial upload" if is_new_protocol else "")
                        ),
                        uploaded_by=(
                            request.user if request.user.is_authenticated else None
                        ),
                    )
                    original_name = os.path.basename(
                        uploaded_file.name or revision_filename
                    )
                    revision_instance.original_name = original_name
                    file_size = getattr(uploaded_file, "size", None)
                    if file_size in (None, ""):
                        file_size = getattr(revision_content, "size", None)
                    try:
                        revision_instance.file_size = int(file_size or 0)
                    except (TypeError, ValueError):
                        revision_instance.file_size = 0
                    revision_instance.file.save(
                        revision_filename, revision_content, save=True
                    )
                    obj.current_revision = revision_instance
                    obj.save(update_fields=["current_revision"])
                elif stage_changed and obj.current_revision:
                    update_fields = []
                    if obj.current_revision.stage != obj.stage:
                        obj.current_revision.stage = obj.stage
                        update_fields.append("stage")
                    if reason:
                        obj.current_revision.change_reason = reason
                        update_fields.append("change_reason")
                    if update_fields:
                        obj.current_revision.save(update_fields=update_fields)

                if obj.stage == "final" and obj.current_revision:
                    ProtocolRevision.objects.filter(protocol=obj).exclude(
                        pk=obj.current_revision_id
                    ).update(stage="draft")
                    if obj.current_revision.stage != "final":
                        obj.current_revision.stage = "final"
                        obj.current_revision.save(update_fields=["stage"])

                detail_parts = []
                if changes:
                    detail_parts.append("; ".join(changes))
                if reason:
                    detail_parts.append(f"Reason: {reason}")
                if not detail_parts:
                    detail_parts.append(
                        "Protocol saved without detectable field changes"
                    )

                _log_project_change(
                    project,
                    request.user,
                    "Protocol updated",
                    " | ".join(detail_parts),
                )
                success_message = "Protocol updated."
                if obj.stage == "final" and (
                    is_new_protocol or stage_changed or replacing_file
                ):
                    success_message = "Protocol updated and marked as final. Switch to Draft before uploading further revisions."
                messages.success(request, success_message)
                return redirect("synopsis:protocol_detail", project_id=project.id)
    else:
        form = ProtocolUpdateForm(instance=protocol)

    if first_upload_pending:
        form.fields["change_reason"].help_text = (
            "Optional for the first upload. Provide details when you revise an existing protocol."
        )
    else:
        form.fields["change_reason"].help_text = (
            "Required when you replace the file or change the protocol stage."
        )

    return render(
        request,
        "synopsis/protocol_detail.html",
        {
            "project": project,
            "protocol": protocol,
            "form": form,
            "protocol_history_entries": protocol_history_entries,
            "protocol_revision_entries": revision_entries,
            "current_revision_entry": current_revision_entry,
            "current_revision_download_url": current_revision_download_url,
            "final_stage_locked": final_stage_locked,
            "first_upload_pending": first_upload_pending,
            "can_manage_project": can_manage,
            "can_edit_documents": can_edit_documents,
            "collaborative_enabled": collaborative_enabled,
            "collaborative_session": collaborative_session,
            "collaborative_start_url": reverse(
                "synopsis:collaborative_start", args=[project.id, collaborative_slug]
            ),
            "collaborative_resume_url": collaborative_resume_url,
            "collaborative_force_end_url": collaborative_force_end_url,
            "collaborative_document_ready": protocol_document_ready,
            "collaborative_can_override": collaborative_can_override,
        },
    )


@login_required
def action_list_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    action_list = getattr(project, "action_list", None)
    can_manage = _user_is_manager(request.user)
    can_edit_documents = _user_can_edit_project(request.user, project)
    history_queryset = (
        project.change_log.filter(action__icontains="action list")
        .select_related("changed_by")
        .order_by("-created_at", "-id")
    )
    history_entries = []
    for log in history_queryset:
        segments = [
            segment.strip() for segment in log.details.split("|") if segment.strip()
        ]
        reason = ""
        changes = []
        for segment in segments:
            if segment.lower().startswith("reason:"):
                reason = segment.split(":", 1)[1].strip()
            else:
                changes.append(segment)
        history_entries.append(
            {
                "log": log,
                "changes": changes,
                "reason": reason,
                "actor": _user_display(log.changed_by) if log.changed_by else "System",
            }
        )

    revision_entries = []
    if action_list:
        revision_queryset = action_list.revisions.select_related("uploaded_by")
        for revision in revision_queryset:
            file_name = revision.original_name or os.path.basename(revision.file.name)
            try:
                download_url = revision.file.url
            except ValueError:
                download_url = ""
            revision_entries.append(
                {
                    "revision": revision,
                    "is_current": action_list.current_revision_id == revision.id,
                    "file_name": file_name,
                    "file_size": _format_file_size(revision.file_size),
                    "uploaded_by": (
                        _user_display(revision.uploaded_by)
                        if revision.uploaded_by
                        else "—"
                    ),
                    "download_url": download_url,
                    "can_mark_final": can_manage
                    and (
                        action_list.stage != "final"
                        or action_list.current_revision_id != revision.id
                    ),
                }
            )

    current_revision_entry = next(
        (entry for entry in revision_entries if entry["is_current"]), None
    )
    current_revision_download_url = ""
    if current_revision_entry:
        try:
            current_revision_download_url = current_revision_entry["revision"].file.url
        except ValueError:
            current_revision_download_url = ""

    action_document_ready = bool(action_list and getattr(action_list, "document", None))
    existing_file_name = action_list.document.name if action_document_ready else ""
    has_existing_file = bool(existing_file_name or revision_entries)
    first_upload_pending = not has_existing_file
    final_stage_locked = bool(
        action_list and action_list.stage == "final" and has_existing_file
    )

    collaborative_enabled = _onlyoffice_enabled()
    action_closed = bool(action_list and action_list.feedback_closed_at)
    collaborative_session = None
    collaborative_resume_url = ""
    collaborative_force_end_url = ""
    collaborative_slug = _document_type_slug(CollaborativeSession.DOCUMENT_ACTION_LIST)
    if collaborative_enabled:
        collaborative_session = _get_active_collaborative_session(
            project, CollaborativeSession.DOCUMENT_ACTION_LIST
        )
        if collaborative_session and action_closed:
            collaborative_session.mark_inactive(
                ended_by=request.user if request.user.is_authenticated else None,
                reason="Action list feedback window closed",
            )
            collaborative_session = None
        if collaborative_session:
            collaborative_resume_url = reverse(
                "synopsis:collaborative_edit",
                args=[project.id, collaborative_slug, collaborative_session.token],
            )
            collaborative_force_end_url = reverse(
                "synopsis:collaborative_force_end",
                args=[project.id, collaborative_slug, collaborative_session.token],
            )
    if collaborative_session:
        collaborative_can_override = _user_can_force_end_session(
            request.user, project, collaborative_session
        )
    else:
        collaborative_can_override = False
    if action_closed:
        collaborative_enabled = False
        collaborative_session = None
        collaborative_resume_url = ""
        collaborative_force_end_url = ""
        collaborative_can_override = False

    if request.method == "POST":
        form = ActionListUpdateForm(request.POST, request.FILES, instance=action_list)
        if form.is_valid():
            new_stage = form.cleaned_data.get("stage")
            uploaded_file = form.cleaned_data.get("document")
            reason = form.cleaned_data.get("change_reason", "")

            is_new_action_list = action_list is None
            stage_changed = bool(action_list) and action_list.stage != new_stage
            replacing_file = bool(uploaded_file)

            if final_stage_locked and new_stage == "final" and replacing_file:
                form.add_error(
                    "document",
                    "Finalized action lists cannot be replaced. Switch the stage back to Draft to revise the document.",
                )

            needs_reason = (not is_new_action_list) and (
                stage_changed or replacing_file
            )
            if needs_reason and not reason:
                form.add_error(
                    "change_reason",
                    "Please capture the reason for this revision so the team has context.",
                )

            if not form.errors:
                old_stage = action_list.stage if action_list else None
                old_file = (
                    action_list.document.name
                    if action_list and action_list.document
                    else None
                )

                revision_content = None
                revision_filename = ""
                if uploaded_file:
                    uploaded_file.seek(0)
                    revision_content = ContentFile(uploaded_file.read())
                    uploaded_file.seek(0)
                    revision_filename = os.path.basename(
                        uploaded_file.name or "action_list_upload"
                    )

                obj = form.save(commit=False)
                obj.project = project
                obj.save()
                form.save_m2m()

                action_list = obj

                new_file = obj.document.name if obj.document else None
                changes = []

                if is_new_action_list:
                    changes.append("Created action list record")
                elif old_stage != obj.stage:
                    changes.append(
                        f"Stage: {_format_value(old_stage)} → {_format_value(obj.stage)}"
                    )

                if old_file != new_file:
                    if new_file and old_file:
                        changes.append(f"File replaced: {old_file} → {new_file}")
                    elif new_file:
                        changes.append(f"File uploaded: {new_file}")
                    elif old_file:
                        changes.append(f"File removed: {old_file}")

                revision_instance = None
                if revision_content is not None:
                    revision_instance = ActionListRevision(
                        action_list=obj,
                        stage=obj.stage,
                        change_reason=(
                            reason
                            if reason
                            else ("Initial upload" if is_new_action_list else "")
                        ),
                        uploaded_by=(
                            request.user if request.user.is_authenticated else None
                        ),
                    )
                    original_name = os.path.basename(
                        uploaded_file.name or revision_filename
                    )
                    revision_instance.original_name = original_name
                    file_size = getattr(uploaded_file, "size", None)
                    if file_size in (None, ""):
                        file_size = getattr(revision_content, "size", None)
                    try:
                        revision_instance.file_size = int(file_size or 0)
                    except (TypeError, ValueError):
                        revision_instance.file_size = 0
                    revision_instance.file.save(
                        revision_filename, revision_content, save=True
                    )
                    obj.current_revision = revision_instance
                    obj.save(update_fields=["current_revision"])
                elif stage_changed and obj.current_revision:
                    update_fields = []
                    if obj.current_revision.stage != obj.stage:
                        obj.current_revision.stage = obj.stage
                        update_fields.append("stage")
                    if reason:
                        obj.current_revision.change_reason = reason
                        update_fields.append("change_reason")
                    if update_fields:
                        obj.current_revision.save(update_fields=update_fields)

                if obj.stage == "final" and obj.current_revision:
                    ActionListRevision.objects.filter(action_list=obj).exclude(
                        pk=obj.current_revision_id
                    ).update(stage="draft")
                    if obj.current_revision.stage != "final":
                        obj.current_revision.stage = "final"
                        obj.current_revision.save(update_fields=["stage"])

                detail_parts = []
                if changes:
                    detail_parts.append("; ".join(changes))
                if reason:
                    detail_parts.append(f"Reason: {reason}")
                if not detail_parts:
                    detail_parts.append(
                        "Action list saved without detectable field changes"
                    )

                _log_project_change(
                    project,
                    request.user,
                    "Action list updated",
                    " | ".join(detail_parts),
                )
                success_message = "Action list updated."
                if obj.stage == "final" and (
                    is_new_action_list or stage_changed or replacing_file
                ):
                    success_message = "Action list updated and marked as final. Switch to Draft before uploading further revisions."
                messages.success(request, success_message)
                return redirect("synopsis:action_list_detail", project_id=project.id)
    else:
        form = ActionListUpdateForm(instance=action_list)

    if first_upload_pending:
        form.fields["change_reason"].help_text = (
            "Optional for the first upload. Provide details when you revise an existing action list."
        )
    else:
        form.fields["change_reason"].help_text = (
            "Required when you replace the file or change the action list stage."
        )

    return render(
        request,
        "synopsis/action_list_detail.html",
        {
            "project": project,
            "action_list": action_list,
            "form": form,
            "action_list_history_entries": history_entries,
            "action_list_revision_entries": revision_entries,
            "current_revision_entry": current_revision_entry,
            "current_revision_download_url": current_revision_download_url,
            "final_stage_locked": final_stage_locked,
            "first_upload_pending": first_upload_pending,
            "can_manage_project": can_manage,
            "can_edit_documents": can_edit_documents,
            "collaborative_enabled": collaborative_enabled,
            "collaborative_session": collaborative_session,
            "collaborative_start_url": reverse(
                "synopsis:collaborative_start", args=[project.id, collaborative_slug]
            ),
            "collaborative_resume_url": collaborative_resume_url,
            "collaborative_force_end_url": collaborative_force_end_url,
            "collaborative_can_override": collaborative_can_override,
            "collaborative_document_ready": action_document_ready,
        },
    )


def _resolve_collaborative_users(user_ids) -> tuple[list[User], list[str]]:
    if not user_ids:
        return [], []

    normalized = [str(uid) for uid in user_ids if uid is not None]
    if not normalized:
        return [], []

    user_id_strings = [key for key in normalized if key.isdigit()]
    member_id_strings = []
    for key in normalized:
        if key.startswith("abm:"):
            try:
                member_id_strings.append(int(key.split(":", 1)[1]))
            except (TypeError, ValueError):
                continue

    users = []
    user_map: dict[str, User] = {}
    if user_id_strings:
        ids = [int(key) for key in user_id_strings]
        for user in User.objects.filter(id__in=ids):
            user_map[str(user.id)] = user

    member_map: dict[str, AdvisoryBoardMember] = {}
    if member_id_strings:
        for member in AdvisoryBoardMember.objects.filter(id__in=member_id_strings):
            member_map[f"abm:{member.id}"] = member

    ordered_users: list[User] = []
    labels: list[str] = []
    seen_users: set[int] = set()

    for key in normalized:
        user = user_map.get(key)
        if user:
            if user.id not in seen_users:
                ordered_users.append(user)
                seen_users.add(user.id)
            labels.append(_user_display(user))
            continue

        member = member_map.get(key)
        if member:
            labels.append(_advisory_member_display(member))
            continue

        if key.startswith("abe:"):
            email_value = key.split(":", 1)[1]
            labels.append(email_value or "Advisory board invitee")
            continue

        if key:
            labels.append(key)

    return ordered_users, labels


def _persist_collaborative_revision(
    document_type,
    document,
    content: bytes,
    original_name: str,
    uploader,
    change_reason: str,
):
    file_length = len(content)
    safe_name = original_name or "document.docx"
    content_file = ContentFile(content)

    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL:
        revision = ProtocolRevision(
            protocol=document,
            stage=document.stage,
            change_reason=change_reason,
            uploaded_by=uploader,
        )
        revision.file.save(safe_name, content_file, save=False)
        revision.original_name = safe_name
        revision.file_size = file_length
        revision.save()
        base_name, size_text = _apply_revision_to_protocol(document, revision)
        if document.stage == "final":
            ProtocolRevision.objects.filter(protocol=document).exclude(
                pk=revision.pk
            ).update(stage="draft")
            if revision.stage != "final":
                revision.stage = "final"
                revision.save(update_fields=["stage"])
        return revision, base_name, size_text

    revision = ActionListRevision(
        action_list=document,
        stage=document.stage,
        change_reason=change_reason,
        uploaded_by=uploader,
    )
    revision.file.save(safe_name, content_file, save=False)
    revision.original_name = safe_name
    revision.file_size = file_length
    revision.save()
    base_name, size_text = _apply_revision_to_action_list(document, revision)
    if document.stage == "final":
        ActionListRevision.objects.filter(action_list=document).exclude(
            pk=revision.pk
        ).update(stage="draft")
        if revision.stage != "final":
            revision.stage = "final"
            revision.save(update_fields=["stage"])
    return revision, base_name, size_text


def _handle_collaborative_save(
    project,
    document_type,
    document,
    session,
    payload: dict,
    status: int,
):
    file_url = payload.get("url")
    if not file_url:
        logger.warning(
            "Collaborative callback missing file URL for session %s", session.pk
        )
        return False

    try:
        content = _download_onlyoffice_file(file_url)
    except requests.RequestException as exc:
        logger.error("Failed to download OnlyOffice file: %s", exc)
        return False

    original_name = payload.get("filename") or os.path.basename(
        getattr(getattr(document, "document", None), "name", "")
    )
    if not original_name:
        original_name = f"{_document_type_slug(document_type)}.docx"

    resolved_users, user_labels = _resolve_collaborative_users(payload.get("users", []))
    uploader = resolved_users[0] if resolved_users else session.started_by
    if not user_labels and session.started_by:
        user_labels.append(_user_display(session.started_by))
    if user_labels:
        session.last_participant_name = user_labels[0]

    change_reason = (payload.get("message") or payload.get("comment") or "").strip()
    if not change_reason:
        qualifier = "force save" if status == 6 else "save"
        if user_labels:
            change_reason = (
                f"Collaborative {qualifier} via OnlyOffice by {', '.join(user_labels)}"
            )
        else:
            change_reason = f"Collaborative {qualifier} via OnlyOffice"

    revision, base_name, size_text = _persist_collaborative_revision(
        document_type,
        document,
        content,
        original_name,
        uploader,
        change_reason,
    )

    document_label = _document_label(document_type)
    detail_parts = [
        f"Session: {session.token}",
        f"Status: {status}",
        f"File: {base_name}",
    ]
    if user_labels:
        detail_parts.append(f"Users: {', '.join(user_labels)}")
    if size_text and size_text != "—":
        detail_parts.append(f"Size: {size_text}")
    detail_parts.append(f"Reason: {change_reason}")

    action_label = f"{document_label} updated via collaborative edit"
    _log_project_change(
        project,
        uploader or session.started_by,
        action_label,
        " | ".join(detail_parts),
    )

    session.change_summary = change_reason
    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL:
        session.result_protocol_revision = revision
        extra_updates = ["change_summary", "result_protocol_revision"]
    else:
        session.result_action_list_revision = revision
        extra_updates = ["change_summary", "result_action_list_revision"]

    if session.last_participant_name:
        extra_updates.append("last_participant_name")

    reason_text = (
        "Document saved from OnlyOffice"
        if status in {2, 6}
        else f"Session closed (status {status})"
    )
    session.mark_inactive(
        ended_by=uploader,
        reason=reason_text,
        extra_updates=extra_updates,
    )
    return True


@login_required
def collaborative_start(request, project_id, document_slug):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    project = get_object_or_404(Project, pk=project_id)
    document_type = _normalize_document_type(document_slug)
    if not document_type:
        raise Http404("Unknown document type")

    if not _onlyoffice_enabled():
        messages.error(
            request,
            "Collaborative editing is not configured. Please contact your administrator.",
        )
        return redirect(_document_detail_url(project.id, document_type))

    if not _user_can_edit_project(request.user, project):
        messages.error(
            request, "You do not have permission to start a collaborative session."
        )
        return redirect(_document_detail_url(project.id, document_type))

    document = _get_document_for_type(project, document_type)
    if not _document_requires_file(document):
        messages.error(
            request,
            f"No {_document_label(document_type).lower()} file is available to edit.",
        )
        return redirect(_document_detail_url(project.id, document_type))

    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL and getattr(
        document, "feedback_closed_at", None
    ):
        _end_active_collaborative_session(
            project,
            document_type,
            ended_by=request.user,
            reason="Protocol feedback window closed",
        )
        messages.info(
            request,
            "Collaborative editing is disabled because the protocol feedback window is closed.",
        )
        return redirect(_document_detail_url(project.id, document_type))

    if document_type == CollaborativeSession.DOCUMENT_ACTION_LIST and getattr(
        document, "feedback_closed_at", None
    ):
        _end_active_collaborative_session(
            project,
            document_type,
            ended_by=request.user,
            reason="Action list feedback window closed",
        )
        messages.info(
            request,
            "Collaborative editing is disabled because the action list feedback window is closed.",
        )
        return redirect(_document_detail_url(project.id, document_type))

    # TODO: #17 need to guard against race conditions by wrapping this check/create in a transaction
    # or enforcing a uniqueness constraint so concurrent POSTs cannot spawn two sessions.
    active_session = _get_active_collaborative_session(project, document_type)
    if active_session:
        messages.warning(
            request,
            "A collaborative session is already running. Opening the existing editor instead.",
        )
        return redirect(
            "synopsis:collaborative_edit",
            project_id=project.id,
            document_slug=_document_type_slug(document_type),
            token=active_session.token,
        )

    initial_revision = None
    if document_type == CollaborativeSession.DOCUMENT_PROTOCOL:
        initial_revision = (
            getattr(document, "current_revision", None) or document.latest_revision()
        )
        session = CollaborativeSession.objects.create(
            project=project,
            document_type=document_type,
            started_by=request.user,
            last_activity_at=timezone.now(),
            initial_protocol_revision=initial_revision,
        )
    else:
        initial_revision = (
            getattr(document, "current_revision", None) or document.latest_revision()
        )
        session = CollaborativeSession.objects.create(
            project=project,
            document_type=document_type,
            started_by=request.user,
            last_activity_at=timezone.now(),
            initial_action_list_revision=initial_revision,
        )

    document_label = _document_label(document_type)
    _log_project_change(
        project,
        request.user,
        f"{document_label} collaborative editing started",
        f"Session {session.token} started by {_user_display(request.user)}",
    )

    messages.success(request, f"{document_label} editor is ready.")
    return redirect(
        "synopsis:collaborative_edit",
        project_id=project.id,
        document_slug=_document_type_slug(document_type),
        token=session.token,
    )


@login_required
def collaborative_edit(request, project_id, document_slug, token):
    project = get_object_or_404(Project, pk=project_id)
    document_type = _normalize_document_type(document_slug)
    if not document_type:
        raise Http404("Unknown document type")

    document_label = _document_label(document_type)
    detail_url = _document_detail_url(project.id, document_type)

    if not _onlyoffice_enabled():
        messages.error(
            request,
            "Collaborative editing is not configured. Please contact your administrator.",
        )
        return redirect(detail_url)

    session = _collaborative_session_or_404(project, document_type, token)
    if session.has_expired():
        session.mark_inactive(reason="Session expired")
        messages.warning(request, "This collaborative session has expired.")
        return redirect(detail_url)

    if not _user_can_edit_project(request.user, project):
        messages.error(request, "You do not have access to this collaborative session.")
        return redirect(detail_url)

    document = _get_document_for_type(project, document_type)
    if not _document_requires_file(document):
        messages.error(
            request,
            f"No {_document_label(document_type).lower()} file is available to edit.",
        )
        return redirect(detail_url)

    if getattr(document, "feedback_closed_at", None):
        if session.is_active:
            session.mark_inactive(
                ended_by=request.user if _user_can_edit_project(request.user, project) else None,
                reason=f"{document_label} feedback window closed",
            )
        closure_message = document.feedback_closure_message or (
            f"Collaborative editing is closed for this {document_label.lower()}."
        )
        return render(
            request,
            "synopsis/collaborative_editor.html",
            {
                "project": project,
                "document_label": document_label,
                "detail_url": detail_url,
                "window_closed_message": closure_message,
                "can_force_end": False,
                "force_end_url": "",
                "participant_display": "",
            },
            status=200,
        )

    if not session.is_active:
        if _user_can_edit_project(request.user, project):
            restart_url = _ensure_collaborative_invite_link(
                request, project, document_type
            )
            if restart_url and restart_url != request.build_absolute_uri():
                messages.info(
                    request,
                    "The previous collaborative session ended. A fresh editor has been opened.",
                )
                return redirect(restart_url)
        messages.info(request, "This collaborative session is no longer active.")
        return redirect(detail_url)

    editor_js_url = _onlyoffice_editor_js_url()
    if not editor_js_url:
        messages.error(
            request,
            "The OnlyOffice editor script URL is not configured. Please contact your administrator.",
        )
        return redirect(_document_detail_url(project.id, document_type))

    participant_member = None
    participant_feedback = None
    feedback_token = request.GET.get("feedback")
    if feedback_token:
        feedback_model = (
            ProtocolFeedback
            if document_type == CollaborativeSession.DOCUMENT_PROTOCOL
            else ActionListFeedback
        )
        feedback_qs = feedback_model.objects.select_related("member")
        try:
            participant_feedback = feedback_qs.get(
                token=feedback_token, project=project
            )
            participant_member = participant_feedback.member
        except feedback_model.DoesNotExist:
            participant_feedback = None
    if not participant_member:
        member_id = request.GET.get("member")
        if member_id:
            try:
                participant_member = AdvisoryBoardMember.objects.get(
                    pk=member_id, project=project
                )
            except AdvisoryBoardMember.DoesNotExist:
                participant_member = None

    participant_display = ""
    participant_context = None
    if participant_member:
        participant_display = _advisory_member_display(participant_member)
        participant_context = {
            "id": f"abm:{participant_member.id}",
            "name": participant_display,
            "email": participant_member.email,
        }
    elif participant_feedback and participant_feedback.email:
        participant_display = participant_feedback.email
        participant_context = {
            "id": f"abe:{participant_feedback.email.lower()}",
            "name": participant_display,
            "email": participant_feedback.email,
        }

    try:
        config = _build_onlyoffice_config(
            request,
            project,
            document,
            session,
            document_type,
            participant=participant_context,
        )
    except ValueError as exc:
        messages.error(request, str(exc))
        return redirect(_document_detail_url(project.id, document_type))

    session.last_activity_at = timezone.now()
    update_fields = ["last_activity_at"]
    if participant_display:
        session.last_participant_name = participant_display
        update_fields.append("last_participant_name")
    session.save(update_fields=update_fields)

    force_end_url = reverse(
        "synopsis:collaborative_force_end",
        args=[project.id, _document_type_slug(document_type), session.token],
    )
    can_force_end = _user_can_force_end_session(request.user, project, session)

    return render(
        request,
        "synopsis/collaborative_editor.html",
        {
            "project": project,
            "session": session,
            "document_label": document_label,
            "editor_config": config,
            "onlyoffice_js_url": editor_js_url,
            "detail_url": _document_detail_url(project.id, document_type),
            "can_force_end": can_force_end,
            "force_end_url": force_end_url,
            "participant_display": participant_display,
        },
    )


@login_required
def collaborative_force_end(request, project_id, document_slug, token):
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    project = get_object_or_404(Project, pk=project_id)
    document_type = _normalize_document_type(document_slug)
    if not document_type:
        raise Http404("Unknown document type")

    session = _collaborative_session_or_404(project, document_type, token)
    if not session.is_active:
        messages.info(request, "The collaborative session is already closed.")
        return redirect(_document_detail_url(project.id, document_type))

    if not _user_can_force_end_session(request.user, project, session):
        messages.error(request, "You cannot override this collaborative lock.")
        return redirect(_document_detail_url(project.id, document_type))

    reason = (request.POST.get("reason") or "").strip() or "Session ended from portal"
    session.change_summary = session.change_summary or reason
    session.mark_inactive(
        ended_by=request.user,
        reason=reason,
        extra_updates=["change_summary"],
    )

    document_label = _document_label(document_type)
    _log_project_change(
        project,
        request.user,
        f"{document_label} collaborative session ended",
        f"Session {session.token} ended manually ({reason}).",
    )
    messages.success(request, f"{document_label} collaborative session closed.")
    return redirect(_document_detail_url(project.id, document_type))


@csrf_exempt
def collaborative_edit_callback(request, project_id, document_slug, token):
    if request.method != "POST":
        return JsonResponse({"error": 1, "message": "POST required"}, status=405)

    project = get_object_or_404(Project, pk=project_id)
    document_type = _normalize_document_type(document_slug)
    if not document_type:
        return JsonResponse({"error": 1, "message": "Unknown document"}, status=404)

    session = _collaborative_session_or_404(project, document_type, token)

    try:
        payload = _parse_onlyoffice_callback(request)
    except PermissionDenied:
        raise
    except ValueError:
        return JsonResponse({"error": 1, "message": "Invalid payload"}, status=400)

    status = payload.get("status")
    try:
        status = int(status)
    except (TypeError, ValueError):
        status = 0

    session.record_callback(payload)

    document = _get_document_for_type(project, document_type)
    if not _document_requires_file(document):
        session.mark_inactive(reason="Document missing at save time")
        return JsonResponse({"error": 0})

    if status in {2, 6}:
        success = _handle_collaborative_save(
            project, document_type, document, session, payload, status
        )
        if not success:
            return JsonResponse({"error": 1})
        return JsonResponse({"error": 0})

    if status in {3, 4, 7}:
        reason_map = {
            3: "Session closed without changes",
            4: "Session closed by timeout",
            7: "Session closed with errors",
        }
        session.mark_inactive(reason=reason_map.get(status, "Session closed"))
        _log_project_change(
            project,
            session.started_by,
            f"{_document_label(document_type)} collaborative session closed",
            f"Session {session.token} closed (status {status}).",
        )
        return JsonResponse({"error": 0})

    return JsonResponse({"error": 0})


@login_required
def action_list_set_stage(request, project_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method.")

    project = get_object_or_404(Project, pk=project_id)
    if not _user_is_manager(request.user):
        messages.error(
            request, "You do not have permission to update the action list stage."
        )
        return redirect("synopsis:action_list_detail", project_id=project.id)

    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.error(request, "No action list exists yet.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    target_stage = (request.POST.get("stage") or "").strip()
    if target_stage not in {"draft", "final"}:
        return HttpResponseBadRequest("Invalid stage value.")

    reason = (request.POST.get("reason") or "").strip()
    old_stage = action_list.stage

    revision = None
    revision_id = request.POST.get("revision_id")
    if revision_id:
        revision = get_object_or_404(
            ActionListRevision, pk=revision_id, action_list=action_list
        )
    elif action_list.current_revision:
        revision = action_list.current_revision
    else:
        revision = action_list.revisions.order_by("-uploaded_at", "-id").first()

    if action_list.stage == target_stage and not (
        target_stage == "final"
        and revision
        and action_list.current_revision
        and revision.id != action_list.current_revision_id
    ):
        messages.info(request, f"Action list is already marked as {target_stage}.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    if target_stage == "final":
        if not revision:
            messages.error(
                request,
                "No revision found to mark as final. Please upload an action list first.",
            )
            return redirect("synopsis:action_list_detail", project_id=project.id)
        if not reason:
            messages.error(
                request,
                "Please provide a brief reason for marking the action list as final.",
            )
            return redirect("synopsis:action_list_detail", project_id=project.id)

        try:
            base_name, size_text = _apply_revision_to_action_list(action_list, revision)
        except FileNotFoundError:
            messages.error(
                request,
                "The selected revision file could not be found. Please choose another revision or upload a new version.",
            )
            return redirect("synopsis:action_list_detail", project_id=project.id)
        except ValueError:
            messages.error(
                request,
                "The selected revision file is empty. Please choose another revision or upload a new version.",
            )
            return redirect("synopsis:action_list_detail", project_id=project.id)

        action_list.stage = "final"
        action_list.save(update_fields=["stage"])

        ActionListRevision.objects.filter(action_list=action_list).exclude(
            pk=revision.pk
        ).update(stage="draft")
        update_fields = ["stage"]
        if revision.stage != "final":
            revision.stage = "final"
        if reason:
            revision.change_reason = reason
            if "change_reason" not in update_fields:
                update_fields.append("change_reason")
        revision.save(update_fields=update_fields)

        detail_parts = [
            f"Stage: {_format_value(old_stage)} → Final",
            f"File: {base_name}",
        ]
        if size_text != "—":
            detail_parts.append(f"Size: {size_text}")
        if reason:
            detail_parts.append(f"Reason: {reason}")

        _log_project_change(
            project,
            request.user,
            "Action list marked final",
            " | ".join(detail_parts),
        )

        messages.success(
            request,
            "Action list marked as final. Switch back to Draft before uploading new revisions.",
        )
        return redirect("synopsis:action_list_detail", project_id=project.id)

    action_list.stage = "draft"
    action_list.save(update_fields=["stage"])
    if action_list.current_revision and action_list.current_revision.stage != "draft":
        action_list.current_revision.stage = "draft"
        action_list.current_revision.save(update_fields=["stage"])

    detail_parts = [f"Stage: {_format_value(old_stage)} → Draft"]
    if reason:
        detail_parts.append(f"Reason: {reason}")

    _log_project_change(
        project,
        request.user,
        "Action list stage updated",
        " | ".join(detail_parts),
    )

    messages.success(request, "Action list stage set to draft.")
    return redirect("synopsis:action_list_detail", project_id=project.id)


# TODO: #18 Investigate bug where uploading a new action list after deleting the file does not refresh the page with the latest document.
@login_required
def action_list_delete_file(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list or not action_list.document:
        messages.info(request, "No action list file to delete.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    if request.method == "POST":
        file_name = action_list.document.name
        action_list.document.delete(save=False)
        action_list.document = ""
        action_list.current_revision = None
        action_list.save(update_fields=["document", "current_revision"])
        _log_project_change(
            project,
            request.user,
            "Removed action list file",
            f"File: {file_name}",
        )
        messages.success(request, "Action list file removed.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    return render(
        request,
        "synopsis/action_list_confirm_delete.html",
        {
            "project": project,
            "action_list": action_list,
            "mode": "file",
        },
    )


@login_required
def action_list_restore_revision(request, project_id, revision_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method.")

    project = get_object_or_404(Project, pk=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.error(request, "No action list exists to restore.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    revision = get_object_or_404(
        ActionListRevision, pk=revision_id, action_list=action_list
    )

    try:
        base_name, size_text = _apply_revision_to_action_list(action_list, revision)
    except FileNotFoundError:
        messages.error(
            request,
            "The selected revision file could not be found. Please upload a new version instead.",
        )
        return redirect("synopsis:action_list_detail", project_id=project.id)
    except ValueError:
        messages.error(
            request,
            "The selected revision file is empty. Please choose another revision or upload a new version.",
        )
        return redirect("synopsis:action_list_detail", project_id=project.id)

    action_list.stage = revision.stage
    action_list.save(update_fields=["stage"])

    restored_at = timezone.localtime(revision.uploaded_at).strftime("%Y-%m-%d %H:%M")
    detail_parts = [
        f"Restored revision uploaded {restored_at}",
        f"Stage reset to {_format_value(revision.stage)}",
        f"File: {base_name}",
    ]
    if size_text != "—":
        detail_parts.append(f"Size: {size_text}")
    if revision.change_reason:
        detail_parts.append(f"Original reason: {revision.change_reason}")

    _log_project_change(
        project,
        request.user,
        "Action list restored",
        " | ".join(detail_parts),
    )

    messages.success(request, "Action list reverted to the selected revision.")
    return redirect("synopsis:action_list_detail", project_id=project.id)


@login_required
def action_list_clear_text(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list or not (action_list.text_version or "").strip():
        messages.info(request, "No action list notes to clear.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    if request.method == "POST":
        old_length = len(action_list.text_version or "")
        action_list.text_version = ""
        action_list.save(update_fields=["text_version"])
        _log_project_change(
            project,
            request.user,
            "Cleared action list notes",
            f"Removed rich text content (previous length {old_length} chars)",
        )
        messages.success(request, "Action list notes cleared.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    return render(
        request,
        "synopsis/action_list_confirm_delete.html",
        {
            "project": project,
            "action_list": action_list,
            "mode": "text",
        },
    )


@login_required
def action_list_delete(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.info(request, "No action list to delete.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    if request.method == "POST":
        file_name = action_list.document.name if action_list.document else None
        text_len = len(action_list.text_version or "")
        revision_count = action_list.revisions.count()
        if action_list.document:
            action_list.document.delete(save=False)
        action_list.delete()
        details = []
        if file_name:
            details.append(f"File: {file_name}")
        details.append(f"Text length removed: {text_len} chars")
        details.append(f"Revisions removed: {revision_count}")
        _log_project_change(
            project,
            request.user,
            "Deleted action list",
            "; ".join(details),
        )
        messages.success(request, "Action list deleted.")
        return redirect("synopsis:project_hub", project_id=project.id)

    return render(
        request,
        "synopsis/action_list_confirm_delete.html",
        {
            "project": project,
            "action_list": action_list,
            "mode": "delete",
        },
    )


@login_required
def protocol_set_stage(request, project_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method.")

    project = get_object_or_404(Project, pk=project_id)
    if not _user_is_manager(request.user):
        messages.error(
            request, "You do not have permission to update the protocol stage."
        )
        return redirect("synopsis:protocol_detail", project_id=project.id)
    protocol = getattr(project, "protocol", None)
    if not protocol:
        messages.error(request, "No protocol exists yet.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    target_stage = (request.POST.get("stage") or "").strip()
    if target_stage not in {"draft", "final"}:
        return HttpResponseBadRequest("Invalid stage value.")

    reason = (request.POST.get("reason") or "").strip()
    old_stage = protocol.stage

    revision = None
    revision_id = request.POST.get("revision_id")
    if revision_id:
        revision = get_object_or_404(
            ProtocolRevision, pk=revision_id, protocol=protocol
        )
    elif protocol.current_revision:
        revision = protocol.current_revision
    else:
        revision = protocol.revisions.order_by("-uploaded_at", "-id").first()

    if protocol.stage == target_stage and not (
        target_stage == "final"
        and revision
        and protocol.current_revision
        and revision.id != protocol.current_revision_id
    ):
        messages.info(request, f"Protocol is already marked as {target_stage}.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    if target_stage == "final":
        if not revision:
            messages.error(
                request,
                "No revision found to mark as final. Please upload a protocol first.",
            )
            return redirect("synopsis:protocol_detail", project_id=project.id)
        if not reason:
            messages.error(
                request,
                "Please provide a brief reason for marking the protocol as final.",
            )
            return redirect("synopsis:protocol_detail", project_id=project.id)

        try:
            base_name, size_text = _apply_revision_to_protocol(protocol, revision)
        except FileNotFoundError:
            messages.error(
                request,
                "The selected revision file could not be found. Please choose another revision or upload a new version.",
            )
            return redirect("synopsis:protocol_detail", project_id=project.id)
        except ValueError:
            messages.error(
                request,
                "The selected revision file is empty. Please choose another revision or upload a new version.",
            )
            return redirect("synopsis:protocol_detail", project_id=project.id)

        protocol.stage = "final"
        protocol.save(update_fields=["stage"])

        ProtocolRevision.objects.filter(protocol=protocol).exclude(
            pk=revision.pk
        ).update(stage="draft")
        update_fields = ["stage"]
        if revision.stage != "final":
            revision.stage = "final"
        if reason:
            revision.change_reason = reason
            if "change_reason" not in update_fields:
                update_fields.append("change_reason")
        revision.save(update_fields=update_fields)

        detail_parts = [
            f"Stage: {_format_value(old_stage)} → Final",
            f"File: {base_name}",
        ]
        if size_text != "—":
            detail_parts.append(f"Size: {size_text}")
        if reason:
            detail_parts.append(f"Reason: {reason}")

        _log_project_change(
            project,
            request.user,
            "Protocol marked final",
            " | ".join(detail_parts),
        )

        messages.success(
            request,
            "Protocol marked as final. Switch back to Draft before uploading new revisions.",
        )
        return redirect("synopsis:protocol_detail", project_id=project.id)

    # target_stage == "draft"
    old_stage = protocol.stage
    protocol.stage = "draft"
    protocol.save(update_fields=["stage"])
    if protocol.current_revision and protocol.current_revision.stage != "draft":
        protocol.current_revision.stage = "draft"
        protocol.current_revision.save(update_fields=["stage"])

    detail_parts = [f"Stage: {_format_value(old_stage)} → Draft"]
    if reason:
        detail_parts.append(f"Reason: {reason}")

    _log_project_change(
        project,
        request.user,
        "Protocol stage updated",
        " | ".join(detail_parts),
    )

    messages.success(request, "Protocol stage set to Draft.")
    return redirect("synopsis:protocol_detail", project_id=project.id)


# TODO: #19 Investigate bug where uploading a new protocol after deleting the file does not refresh the page with the latest document.
@login_required
def protocol_delete_file(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    if not protocol or not protocol.document:
        messages.info(request, "No protocol file to delete.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    if request.method == "POST":
        file_name = protocol.document.name
        protocol.document.delete(save=False)
        protocol.document = ""
        protocol.current_revision = None
        protocol.save(update_fields=["document", "current_revision"])
        _log_project_change(
            project,
            request.user,
            "Removed protocol file",
            f"File: {file_name}",
        )
        messages.success(request, "Protocol file removed.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    return render(
        request,
        "synopsis/protocol_confirm_delete.html",
        {
            "project": project,
            "protocol": protocol,
            "mode": "file",
        },
    )


@login_required
def protocol_delete_revision(request, project_id, revision_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method.")

    project = get_object_or_404(Project, pk=project_id)
    if not _user_can_edit_project(request.user, project):
        messages.error(
            request, "Only assigned authors or managers can delete protocol revisions."
        )
        return redirect("synopsis:protocol_detail", project_id=project.id)

    protocol = getattr(project, "protocol", None)
    if not protocol:
        messages.error(request, "No protocol exists for this project.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    revision = get_object_or_404(ProtocolRevision, pk=revision_id, protocol=protocol)

    was_current = protocol.current_revision_id == revision.id
    file_name = revision.file.name
    revision.delete()

    next_revision = (
        protocol.revisions.exclude(pk=revision_id)
        .order_by("-uploaded_at", "-id")
        .first()
    )

    if was_current:
        if next_revision:
            try:
                base_name, size_text = _apply_revision_to_protocol(
                    protocol, next_revision
                )
            except (FileNotFoundError, ValueError):
                protocol.current_revision = next_revision
                protocol.save(update_fields=["current_revision"])
                base_name = next_revision.original_name or os.path.basename(
                    next_revision.file.name
                )
                size_text = _format_file_size(next_revision.file_size)
        else:
            protocol.current_revision = None
            protocol.save(update_fields=["current_revision"])
            base_name = "none"
            size_text = "—"
    else:
        base_name = revision.original_name or os.path.basename(file_name)
        size_text = _format_file_size(revision.file_size)

    _log_project_change(
        project,
        request.user,
        "Protocol revision deleted",
        f"Revision file: {file_name or 'unknown'}; Remaining current: {base_name} ({size_text})",
    )

    messages.success(request, "Protocol revision deleted.")
    return redirect("synopsis:protocol_detail", project_id=project.id)


@login_required
def protocol_restore_revision(request, project_id, revision_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method.")

    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    if not protocol:
        messages.error(request, "No protocol exists to restore.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    revision = get_object_or_404(ProtocolRevision, pk=revision_id, protocol=protocol)

    try:
        base_name, size_text = _apply_revision_to_protocol(protocol, revision)
    except FileNotFoundError:
        messages.error(
            request,
            "The selected revision file could not be found. Please upload a new version instead.",
        )
        return redirect("synopsis:protocol_detail", project_id=project.id)
    except ValueError:
        messages.error(
            request,
            "The selected revision file is empty. Please choose another revision or upload a new version.",
        )
        return redirect("synopsis:protocol_detail", project_id=project.id)

    protocol.stage = revision.stage
    protocol.save(update_fields=["stage"])

    restored_at = timezone.localtime(revision.uploaded_at).strftime("%Y-%m-%d %H:%M")
    detail_parts = [
        f"Restored revision uploaded {restored_at}",
        f"Stage reset to {_format_value(revision.stage)}",
        f"File: {base_name}",
    ]
    if size_text != "—":
        detail_parts.append(f"Size: {size_text}")
    if revision.change_reason:
        detail_parts.append(f"Original reason: {revision.change_reason}")

    _log_project_change(
        project,
        request.user,
        "Protocol restored",
        " | ".join(detail_parts),
    )

    messages.success(request, "Protocol reverted to the selected revision.")
    return redirect("synopsis:protocol_detail", project_id=project.id)


@login_required
def protocol_clear_text(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    if not protocol or not (protocol.text_version or "").strip():
        messages.info(request, "No protocol text to clear.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    if request.method == "POST":
        old_length = len(protocol.text_version or "")
        protocol.text_version = ""
        protocol.save(update_fields=["text_version"])
        _log_project_change(
            project,
            request.user,
            "Cleared protocol text",
            f"Removed rich text content (previous length {old_length} chars)",
        )
        messages.success(request, "Protocol text cleared.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    return render(
        request,
        "synopsis/protocol_confirm_delete.html",
        {
            "project": project,
            "protocol": protocol,
            "mode": "text",
        },
    )


@login_required
def protocol_delete(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    if not protocol:
        messages.info(request, "No protocol to delete.")
        return redirect("synopsis:protocol_detail", project_id=project.id)

    if request.method == "POST":
        file_name = protocol.document.name if protocol.document else None
        text_len = len(protocol.text_version or "")
        if protocol.document:
            protocol.document.delete(save=False)
        protocol.delete()
        details = []
        if file_name:
            details.append(f"File: {file_name}")
        details.append(f"Text length removed: {text_len} chars")
        _log_project_change(
            project,
            request.user,
            "Deleted protocol",
            "; ".join(details),
        )
        messages.success(request, "Protocol deleted.")
        return redirect("synopsis:project_hub", project_id=project.id)

    return render(
        request,
        "synopsis/protocol_confirm_delete.html",
        {
            "project": project,
            "protocol": protocol,
            "mode": "all",
        },
    )


# TODO: #21 Expand manager's dashboard to include user management features, such as inviting via email, resetting passwords, and modifying global roles.
@login_required
def manager_dashboard(request):
    if not request.user.is_staff:
        messages.error(request, "Manager access only.")
        return redirect("synopsis:dashboard")

    ensure_global_groups()
    users = User.objects.order_by("username")

    projects = Project.objects.prefetch_related("userrole_set__user").order_by(
        "-created_at", "-id"
    )
    project_entries = []
    for project in projects:
        authors = [
            role.user for role in project.userrole_set.all() if role.role == "author"
        ]
        form = ProjectDeleteForm(project=project, auto_id=f"id_project_{project.id}_%s")
        project_entries.append(
            {
                "project": project,
                "authors": authors,
                "delete_form": form,
            }
        )

    return render(
        request,
        "synopsis/manager_dashboard.html",
        {"users": users, "project_entries": project_entries},
    )


@login_required
def project_settings(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if not _user_is_manager(request.user):
        messages.error(request, "Only managers can edit project settings.")
        return redirect("synopsis:project_hub", project_id=project.id)

    if request.method == "POST":
        original_title = project.title
        form = ProjectSettingsForm(request.POST, instance=project, project=project)
        if form.is_valid():
            updated_project = form.save()
            changes = []
            if original_title != updated_project.title:
                changes.append(f"Title: {original_title} → {updated_project.title}")
            if changes:
                _log_project_change(
                    updated_project,
                    request.user,
                    "Updated project settings",
                    "; ".join(changes),
                )
                messages.success(request, "Project settings updated.")
            else:
                messages.info(request, "No changes saved.")
            return redirect("synopsis:project_hub", project_id=project.id)
    else:
        form = ProjectSettingsForm(instance=project, project=project)

    previous_titles = []
    seen_titles = set()

    def add_title_entry(title, changed_at, changed_by, *, is_current=False, note=None):
        title = (title or "").strip()
        if not title or title in seen_titles:
            return
        previous_titles.append(
            {
                "title": title,
                "changed_at": changed_at,
                "changed_by": changed_by,
                "is_current": is_current,
                "note": note or "",
            }
        )
        seen_titles.add(title)

    change_logs = project.change_log.filter(
        action="Updated project settings",
        details__icontains="Title:",
    ).order_by("-created_at")

    for log in change_logs:
        actor = _user_display(log.changed_by) if log.changed_by else "System"
        segments = [
            segment.strip() for segment in log.details.split(";") if segment.strip()
        ]
        for segment in segments:
            if segment.startswith("Title:") and "→" in segment:
                old_part, new_part = segment.split("→", 1)
                old_title = old_part.split("Title:", 1)[1].strip()
                new_title = new_part.strip()
                add_title_entry(
                    new_title,
                    log.created_at,
                    actor,
                    is_current=(
                        new_title == project.title and project.title not in seen_titles
                    ),
                )
                add_title_entry(old_title, log.created_at, actor)

    if project.title not in seen_titles:
        created_at = getattr(project, "created_at", None)
        add_title_entry(
            project.title,
            created_at,
            "Created",
            is_current=True,
            note="Current title",
        )
    context = {
        "project": project,
        "form": form,
        "previous_titles": previous_titles,
    }

    return render(
        request,
        "synopsis/project_settings_form.html",
        context,
    )


# TODO: #20 Implement email verification and password setup workflow for newly created users.
@login_required
def user_create(request):
    if not request.user.is_staff:
        messages.error(request, "Manager access only.")
        return redirect("synopsis:dashboard")

    ensure_global_groups()

    if request.method == "POST":
        form = CreateUserForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].strip().lower()
            password = (
                form.cleaned_data["password"] or User.objects.make_random_password()
            )
            first_name = form.cleaned_data["first_name"].strip()
            last_name = form.cleaned_data["last_name"].strip()
            global_role = form.cleaned_data["global_role"]

            if User.objects.filter(username=email).exists():
                messages.error(request, "A user with that email already exists.")
            else:
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                group = Group.objects.get(name=global_role)
                user.groups.add(group)

                if global_role == "manager":
                    user.is_staff = True
                    user.save(update_fields=["is_staff"])

                messages.success(request, f"User {email} created as {global_role}.")
                return redirect("synopsis:manager_dashboard")
    else:
        form = CreateUserForm()

    return render(request, "synopsis/user_create.html", {"form": form})


# TODO: #22 Add pagination and search functionality to the advisory board member list for improved usability with large datasets.
# TODO: #23 Implement CSV export functionality for advisory board members and their responses.
# TODO: #24 Add email notification functionality for scheduled reminders.
# TODO: #25 Implement role-based access control for advisory board management (or a mechanism for accessing files shared with advisory board members securely such as signed URLs, tokens, etc.).
# TODO: #26 Add ability to edit advisory board member details after creation.
# TODO: #40 Add ability to resend invitations to advisory board members.
# TODO: #39 Add ability to bulk import advisory board members via CSV upload.

@login_required
def advisory_board_list(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if request.method == "POST":
        action = request.POST.get("action")

        if action == "custom_field_add":
            form = AdvisoryCustomFieldForm(project, request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Custom column added to advisory board.")
                return redirect("synopsis:advisory_board_list", project_id=project.id)
            context = _advisory_board_context(
                project,
                user=request.user,
                member_form=AdvisoryBoardMemberForm(),
                custom_field_form=form,
            )
            return render(request, "synopsis/advisory_board_list.html", context)

        if action == "custom_field_delete":
            field_id = request.POST.get("field_id")
            if field_id:
                field = get_object_or_404(
                    AdvisoryBoardCustomField, pk=field_id, project=project
                )
                field.delete()
                messages.info(
                    request,
                    f"Removed custom column '{field.name}'.",
                )
            return redirect("synopsis:advisory_board_list", project_id=project.id)

        if action == "custom_field_move":
            field_id = request.POST.get("field_id")
            field = get_object_or_404(
                AdvisoryBoardCustomField, pk=field_id, project=project
            )
            placement_form = AdvisoryCustomFieldPlacementForm(request.POST)
            if placement_form.is_valid():
                field.display_group = placement_form.cleaned_data["display_group"]
                field.save(update_fields=["display_group"])
                messages.success(
                    request, f"Moved custom column '{field.name}' to a new section."
                )
                return redirect("synopsis:advisory_board_list", project_id=project.id)
            messages.error(request, "Choose a valid section for this column.")
            context = _advisory_board_context(
                project,
                user=request.user,
                member_form=AdvisoryBoardMemberForm(),
                custom_field_form=AdvisoryCustomFieldForm(project),
            )
            return render(request, "synopsis/advisory_board_list.html", context)

        if action == "add_member_confirm":
            form = AdvisoryBoardMemberForm(request.POST)
            if form.is_valid():
                m = form.save(commit=False)
                m.project = project
                m.save()
                messages.success(request, "Advisory Board member added.")
                return redirect("synopsis:advisory_board_list", project_id=project.id)
            context = _advisory_board_context(project, user=request.user, member_form=form)
            return render(request, "synopsis/advisory_board_list.html", context)

        if action == "add_member_back":
            form = AdvisoryBoardMemberForm(request.POST)
            context = _advisory_board_context(project, user=request.user, member_form=form)
            return render(request, "synopsis/advisory_board_list.html", context)

        if action == "add_member":
            form = AdvisoryBoardMemberForm(request.POST)
            if form.is_valid():
                cleaned = form.cleaned_data
                return render(
                    request,
                    "synopsis/advisory_member_confirm.html",
                    {
                        "project": project,
                        "form": form,
                        "cleaned_data": cleaned,
                    },
                )
            context = _advisory_board_context(project, user=request.user, member_form=form)
            return render(request, "synopsis/advisory_board_list.html", context)

    form = AdvisoryBoardMemberForm()
    context = _advisory_board_context(project, user=request.user, member_form=form)
    return render(request, "synopsis/advisory_board_list.html", context)


@login_required
def advisory_schedule_reminders(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = ReminderScheduleForm(request.POST)
    pending_members = project.advisory_board_members.filter(invite_sent=False)

    if not form.is_valid():
        context = _advisory_board_context(project, user=request.user, reminder_form=form)
        return render(request, "synopsis/advisory_board_list.html", context)

    reminder_date = form.cleaned_data["reminder_date"]
    updated = 0
    for member in pending_members:
        member.response_date = reminder_date
        member.reminder_sent = False
        member.save(update_fields=["response_date", "reminder_sent"])
        updated += 1

    if updated:
        _log_project_change(
            project,
            request.user,
            "Scheduled reminders",
            f"Date set to {reminder_date} for {updated} pending member(s)",
        )

    messages.success(request, f"Scheduled reminders for {updated} member(s).")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_schedule_protocol_reminders(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = ProtocolReminderScheduleForm(request.POST)
    pending_members = project.advisory_board_members.filter(
        sent_protocol_at__isnull=False,
        response="Y",
    )

    if not form.is_valid():
        context = _advisory_board_context(project, user=request.user, protocol_form=form)
        return render(request, "synopsis/advisory_board_list.html", context)

    deadline = form.cleaned_data["deadline"]
    if timezone.is_naive(deadline):
        deadline = timezone.make_aware(deadline)
    updated = 0
    for member in pending_members:
        member.feedback_on_protocol_deadline = deadline
        member.protocol_reminder_sent = False
        member.protocol_reminder_sent_at = None
        member.save(
            update_fields=[
                "feedback_on_protocol_deadline",
                "protocol_reminder_sent",
                "protocol_reminder_sent_at",
            ]
        )
        ProtocolFeedback.objects.filter(project=project, member=member).update(
            feedback_deadline_at=deadline
        )
        updated += 1

    skipped_members = project.advisory_board_members.filter(
        sent_protocol_at__isnull=False
    ).exclude(response="Y")
    skipped_ids = list(skipped_members.values_list("id", flat=True))
    if skipped_ids:
        project.advisory_board_members.filter(id__in=skipped_ids).update(
            feedback_on_protocol_deadline=None,
            protocol_reminder_sent=False,
            protocol_reminder_sent_at=None,
        )
        ProtocolFeedback.objects.filter(
            project=project, member_id__in=skipped_ids
        ).update(feedback_deadline_at=None)
        messages.info(
            request,
            "Deadline kept unset for members who have not accepted the invitation yet.",
        )

    if updated:
        _log_project_change(
            project,
            request.user,
            "Scheduled protocol reminders",
            f"Protocol deadline {timezone.localtime(deadline).strftime('%Y-%m-%d %H:%M')} for {updated} member(s)",
        )

    messages.success(
        request,
        f"Protocol reminder scheduled for {updated} member(s). Reminder now set as required.",
    )
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_schedule_action_list_reminders(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    if not getattr(project, "action_list", None):
        messages.error(request, "No action list configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    form = ActionListReminderScheduleForm(request.POST)
    pending_members = project.advisory_board_members.filter(
        sent_action_list_at__isnull=False,
        response="Y",
    )

    if not form.is_valid():
        context = _advisory_board_context(project, user=request.user, action_list_form=form)
        return render(request, "synopsis/advisory_board_list.html", context)

    deadline = form.cleaned_data["deadline"]
    if timezone.is_naive(deadline):
        deadline = timezone.make_aware(deadline)
    updated = 0
    for member in pending_members:
        member.feedback_on_action_list_deadline = deadline
        member.action_list_reminder_sent = False
        member.action_list_reminder_sent_at = None
        member.save(
            update_fields=[
                "feedback_on_action_list_deadline",
                "action_list_reminder_sent",
                "action_list_reminder_sent_at",
            ]
        )
        ActionListFeedback.objects.filter(project=project, member=member).update(
            feedback_deadline_at=deadline
        )
        updated += 1

    skipped_members = project.advisory_board_members.filter(
        sent_action_list_at__isnull=False
    ).exclude(response="Y")
    skipped_ids = list(skipped_members.values_list("id", flat=True))
    if skipped_ids:
        project.advisory_board_members.filter(id__in=skipped_ids).update(
            feedback_on_action_list_deadline=None,
            action_list_reminder_sent=False,
            action_list_reminder_sent_at=None,
        )
        ActionListFeedback.objects.filter(
            project=project, member_id__in=skipped_ids
        ).update(feedback_deadline_at=None)
        messages.info(
            request,
            "Deadline kept unset for members who have not accepted the invitation yet.",
        )

    if updated:
        _log_project_change(
            project,
            request.user,
            "Scheduled action list reminders",
            f"Action list deadline {timezone.localtime(deadline).strftime('%Y-%m-%d %H:%M')} for {updated} member(s)",
        )

    messages.success(
        request,
        f"Action list reminder scheduled for {updated} member(s). Reminder now set as required.",
    )
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_member_set_deadline(request, project_id, member_id, kind):
    project = get_object_or_404(Project, pk=project_id)
    member = get_object_or_404(AdvisoryBoardMember, pk=member_id, project=project)

    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    if not _user_can_edit_project(request.user, project):
        messages.error(request, "You do not have permission to update this member.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    kind = (kind or "").lower().replace("-", "_")
    form_map = {
        "invite": ReminderScheduleForm,
        "protocol": ProtocolReminderScheduleForm,
        "action_list": ActionListReminderScheduleForm,
    }
    if kind not in form_map:
        return HttpResponseBadRequest("Unknown reminder type")

    clearing = request.POST.get("clear_deadline")
    response_code = (member.response or "").upper()

    if kind == "invite" and response_code == "N":
        messages.info(
            request,
            "Reminders are skipped for members who declined the invitation.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    if kind == "protocol":
        if member.sent_protocol_at is None or response_code != "Y":
            messages.error(
                request,
                "This member needs an accepted invitation and a sent protocol before setting a protocol deadline.",
            )
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    if kind == "action_list":
        if not getattr(project, "action_list", None):
            messages.error(request, "No action list configured for this project.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
        if member.sent_action_list_at is None or response_code != "Y":
            messages.error(
                request,
                "This member needs an accepted invitation and the action list before setting an action list deadline.",
            )
            return redirect("synopsis:advisory_board_list", project_id=project.id)

    value = None
    if not clearing:
        form = form_map[kind](request.POST)
        if not form.is_valid():
            error_messages = ", ".join(
                {" ".join(err_list) for err_list in form.errors.values()}
            )
            messages.error(
                request,
                f"Could not update reminder: {error_messages or 'Invalid data.'}",
            )
            return redirect("synopsis:advisory_board_list", project_id=project.id)
        if kind == "invite":
            value = form.cleaned_data["reminder_date"]
        else:
            value = form.cleaned_data["deadline"]
            if timezone.is_naive(value):
                value = timezone.make_aware(value)

    human_name = " ".join(
        part for part in (member.first_name, member.last_name) if part
    ).strip() or member.email

    if kind == "invite":
        member.response_date = value if not clearing else None
        member.reminder_sent = False
        member.reminder_sent_at = None
        member.save(update_fields=["response_date", "reminder_sent", "reminder_sent_at"])
        detail = (
            f"Response deadline {value} for {human_name}"
            if not clearing
            else f"Cleared response deadline for {human_name}"
        )
        _log_project_change(project, request.user, "Updated invite reminder", detail)
        messages.success(
            request,
            "Response deadline updated."
            if not clearing
            else "Response deadline cleared.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    if kind == "protocol":
        member.feedback_on_protocol_deadline = value if not clearing else None
        member.protocol_reminder_sent = False
        member.protocol_reminder_sent_at = None
        member.save(
            update_fields=[
                "feedback_on_protocol_deadline",
                "protocol_reminder_sent",
                "protocol_reminder_sent_at",
            ]
        )
        ProtocolFeedback.objects.filter(project=project, member=member).update(
            feedback_deadline_at=value if not clearing else None
        )
        detail_value = (
            timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else None
        )
        detail = (
            f"Protocol deadline {detail_value} for {human_name}"
            if not clearing
            else f"Cleared protocol deadline for {human_name}"
        )
        _log_project_change(
            project,
            request.user,
            "Updated protocol reminder",
            detail,
        )
        messages.success(
            request,
            "Protocol deadline updated."
            if not clearing
            else "Protocol deadline cleared.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    # action list
    member.feedback_on_action_list_deadline = value if not clearing else None
    member.action_list_reminder_sent = False
    member.action_list_reminder_sent_at = None
    member.save(
        update_fields=[
            "feedback_on_action_list_deadline",
            "action_list_reminder_sent",
            "action_list_reminder_sent_at",
        ]
    )
    ActionListFeedback.objects.filter(project=project, member=member).update(
        feedback_deadline_at=value if not clearing else None
    )
    detail_value = (
        timezone.localtime(value).strftime("%Y-%m-%d %H:%M") if value else None
    )
    detail = (
        f"Action list deadline {detail_value} for {human_name}"
        if not clearing
        else f"Cleared action list deadline for {human_name}"
    )
    _log_project_change(
        project,
        request.user,
        "Updated action list reminder",
        detail,
    )
    messages.success(
        request,
        "Action list deadline updated."
        if not clearing
        else "Action list deadline cleared.",
    )
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_member_edit(request, project_id, member_id):
    project = get_object_or_404(Project, pk=project_id)
    member = get_object_or_404(AdvisoryBoardMember, pk=member_id, project=project)

    if not _user_can_edit_project(request.user, project):
        messages.error(request, "You do not have permission to update this member.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    if request.method == "POST":
        form = AdvisoryBoardMemberForm(request.POST, instance=member)
        if form.is_valid():
            updated_member = form.save()
            display_name = f"{updated_member.first_name} {updated_member.last_name or ''}".strip() or updated_member.email
            _log_project_change(
                project,
                request.user,
                "Updated advisory member",
                f"Edited details for {display_name}",
            )
            messages.success(request, "Member details updated.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = AdvisoryBoardMemberForm(instance=member)

    return render(
        request,
        "synopsis/advisory_member_edit.html",
        {
            "project": project,
            "member": member,
            "form": form,
        },
    )


@login_required
def reference_batch_list(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    batches_qs = project.reference_batches.select_related("uploaded_by").order_by(
        "-created_at", "-id"
    )
    batches = list(batches_qs)
    project_references = project.references.select_related("screened_by")

    status_counts = {
        row["screening_status"]: row["count"]
        for row in project_references.values("screening_status").annotate(
            count=Count("id")
        )
    }
    included_count = status_counts.get("included", 0)
    excluded_count = status_counts.get("excluded", 0)
    pending_count = status_counts.get("pending", 0)
    total_references = project_references.count()
    screened_count = included_count + excluded_count
    completion_percent = (
        round((screened_count / total_references) * 100)
        if total_references
        else 0
    )

    latest_screening = (
        project_references.exclude(screening_decision_at__isnull=True)
        .order_by("-screening_decision_at")
        .first()
    )

    batch_stats = defaultdict(
        lambda: {"included": 0, "excluded": 0, "pending": 0, "total": 0}
    )
    for row in project_references.values("batch_id", "screening_status").annotate(
        count=Count("id")
    ):
        batch_id = row["batch_id"]
        if batch_id is None:
            continue
        stats = batch_stats[batch_id]
        stats["total"] += row["count"]
        status = row["screening_status"]
        if status == "included":
            stats["included"] += row["count"]
        elif status == "excluded":
            stats["excluded"] += row["count"]
        else:
            stats["pending"] += row["count"]

    for batch in batches:
        stats = batch_stats.get(batch.id, {"included": 0, "excluded": 0, "pending": 0, "total": 0})
        screened = stats["included"] + stats["excluded"]
        total = stats["total"]
        batch.screened_count = screened
        batch.total_references = total
        batch.pending_count = stats["pending"]
        batch.included_count = stats["included"]
        batch.excluded_count = stats["excluded"]
        batch.progress_percent = (
            round((screened / total) * 100) if total else 0
        )

    summary = {
        "total": total_references,
        "screened": screened_count,
        "included": included_count,
        "excluded": excluded_count,
        "pending": pending_count,
        "completion_percent": completion_percent,
        "last_screened_at": latest_screening.screening_decision_at
        if latest_screening
        else None,
        "last_screened_by": latest_screening.screened_by
        if latest_screening
        else None,
    }

    return render(
        request,
        "synopsis/reference_batch_list.html",
        {
            "project": project,
            "batches": batches,
            "summary": summary,
        },
    )


@login_required
def reference_batch_detail(request, project_id, batch_id):
    project = get_object_or_404(Project, pk=project_id)
    batch = get_object_or_404(ReferenceSourceBatch, pk=batch_id, project=project)

    references = batch.references.select_related("screened_by").order_by("title")
    status_filter = request.GET.get("status")
    if status_filter in dict(Reference.SCREENING_STATUS_CHOICES):
        references = references.filter(screening_status=status_filter)

    if request.method == "POST":
        action_type = request.POST.get("action")
        if action_type == "update_notes":
            if not _user_can_edit_project(request.user, project):
                raise PermissionDenied
            new_notes = (request.POST.get("notes") or "").strip()
            current_notes = batch.notes or ""
            status_filter = request.POST.get("status_filter") or status_filter or ""
            if new_notes == current_notes:
                messages.info(request, "Notes unchanged.")
            else:
                ReferenceSourceBatchNoteHistory.objects.create(
                    batch=batch,
                    previous_notes=current_notes,
                    new_notes=new_notes,
                    changed_by=request.user if request.user.is_authenticated else None,
                )
                batch.notes = new_notes
                batch.save(update_fields=["notes"])
                messages.success(request, "Batch notes updated.")

            redirect_url = reverse(
                "synopsis:reference_batch_detail",
                kwargs={"project_id": project.id, "batch_id": batch.id},
            )
            if status_filter in dict(Reference.SCREENING_STATUS_CHOICES):
                redirect_url = f"{redirect_url}?status={status_filter}"
            return redirect(redirect_url)

        bulk_action = request.POST.get("bulk_action")
        if bulk_action:
            if not _user_can_edit_project(request.user, project):
                raise PermissionDenied

            status_choices = dict(Reference.SCREENING_STATUS_CHOICES)
            status_filter = (
                request.POST.get("status_filter")
                or request.GET.get("status")
                or ""
            )
            selected_ids = [
                pk
                for pk in request.POST.getlist("selected_references")
                if pk.isdigit()
            ]

            if not selected_ids:
                messages.warning(
                    request,
                    "Select at least one reference before applying a bulk update.",
                )
                redirect_url = reverse(
                    "synopsis:reference_batch_detail",
                    kwargs={"project_id": project.id, "batch_id": batch.id},
                )
                if status_filter in status_choices:
                    redirect_url = f"{redirect_url}?status={status_filter}"
                return redirect(redirect_url)

            action_map = {
                "include": "included",
                "exclude": "excluded",
                "pending": "pending",
            }
            new_status = action_map.get(bulk_action)
            if not new_status:
                messages.error(
                    request,
                    "Unknown bulk action requested.",
                )
                return redirect(
                    "synopsis:reference_batch_detail",
                    project_id=project.id,
                    batch_id=batch.id,
                )

            updated = 0
            now = timezone.now()
            for ref in batch.references.filter(pk__in=selected_ids):
                ref.screening_status = new_status
                ref.screening_decision_at = now
                if request.user.is_authenticated:
                    ref.screened_by = request.user
                ref.save(
                    update_fields=[
                        "screening_status",
                        "screening_decision_at",
                        "screened_by",
                        "updated_at",
                    ]
                )
                updated += 1

            if updated:
                status_label = status_choices.get(new_status, new_status.title())
                messages.success(
                    request,
                    f"Marked {updated} reference(s) as {status_label}.",
                )
            else:
                messages.info(request, "No references matched the selection.")

            redirect_url = reverse(
                "synopsis:reference_batch_detail",
                kwargs={"project_id": project.id, "batch_id": batch.id},
            )
            if status_filter in status_choices:
                redirect_url = f"{redirect_url}?status={status_filter}"
            return redirect(redirect_url)

        form = ReferenceScreeningForm(request.POST)
        if form.is_valid():
            ref = get_object_or_404(
                Reference,
                pk=form.cleaned_data["reference_id"],
                batch=batch,
                project=project,
            )
            status = form.cleaned_data["screening_status"]
            notes = form.cleaned_data.get("screening_notes") or ""
            ref.screening_status = status
            ref.screening_notes = notes
            ref.screening_decision_at = timezone.now()
            ref.screened_by = request.user
            ref.save(
                update_fields=[
                    "screening_status",
                    "screening_notes",
                    "screening_decision_at",
                    "screened_by",
                    "updated_at",
                ]
            )
            messages.success(
                request, f"Updated screening status for '{ref.title[:80]}'."
            )
            redirect_url = reverse(
                "synopsis:reference_batch_detail",
                kwargs={"project_id": project.id, "batch_id": batch.id},
            )
            if status_filter:
                redirect_url = f"{redirect_url}?status={status_filter}"
            return redirect(redirect_url)
        else:
            messages.error(
                request,
                "Unable to update screening status. Please check the submission.",
            )
    status_counts = {
        row["screening_status"]: row["count"]
        for row in batch.references.values("screening_status").annotate(
            count=Count("id")
        )
    }
    status_summary = [
        {
            "status": value,
            "label": label,
            "count": status_counts.get(value, 0),
        }
        for value, label in Reference.SCREENING_STATUS_CHOICES
    ]
    included_count = status_counts.get("included", 0)
    excluded_count = status_counts.get("excluded", 0)
    pending_count = status_counts.get("pending", 0)
    screened_count = included_count + excluded_count
    total_references = batch.references.count()
    completion_percent = (
        round((screened_count / total_references) * 100) if total_references else 0
    )

    visible_total = references.count()
    visible_screened = (
        references.filter(screening_status__in=["included", "excluded"]).count()
        if visible_total
        else 0
    )
    visible_completion = (
        round((visible_screened / visible_total) * 100) if visible_total else 0
    )

    latest_screening = (
        batch.references.exclude(screening_decision_at__isnull=True)
        .select_related("screened_by")
        .order_by("-screening_decision_at")
        .first()
    )

    summary_stats = {
        "included": included_count,
        "excluded": excluded_count,
        "pending": pending_count,
        "screened": screened_count,
        "total": total_references,
        "completion_percent": completion_percent,
        "visible_total": visible_total,
        "visible_screened": visible_screened,
        "visible_completion": visible_completion,
        "has_filter": bool(status_filter),
        "last_screened_at": latest_screening.screening_decision_at
        if latest_screening
        else None,
        "last_screened_by": latest_screening.screened_by
        if latest_screening
        else None,
    }

    return render(
        request,
        "synopsis/reference_batch_detail.html",
        {
            "project": project,
            "batch": batch,
            "references": references,
            "status_filter": status_filter,
            "status_choices": Reference.SCREENING_STATUS_CHOICES,
            "status_summary": status_summary,
            "summary_stats": summary_stats,
            "note_history": batch.note_history.select_related("changed_by").all(),
        },
    )


@login_required
def reference_delete(request, project_id, reference_id):
    project = get_object_or_404(Project, pk=project_id)
    reference = get_object_or_404(
        Reference.objects.select_related("batch"),
        pk=reference_id,
        project=project,
    )

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    if not _user_can_edit_project(request.user, project):
        raise PermissionDenied

    batch = reference.batch
    status_choices = dict(Reference.SCREENING_STATUS_CHOICES)
    status_filter = (
        request.POST.get("status_filter")
        or request.GET.get("status")
        or ""
    )

    title_fragment = reference.title[:80]
    reference.delete()

    batch.record_count = batch.references.count()
    batch.save(update_fields=["record_count"])

    messages.success(
        request,
        f"Removed '{title_fragment}' from '{batch.label}'.",
    )

    redirect_url = reverse(
        "synopsis:reference_batch_detail",
        kwargs={"project_id": project.id, "batch_id": batch.id},
    )
    if status_filter in status_choices:
        redirect_url = f"{redirect_url}?status={status_filter}"

    parsed_redirect = urlparse(redirect_url)
    if parsed_redirect.scheme or parsed_redirect.netloc:
        redirect_url = reverse(
            "synopsis:reference_batch_detail",
            kwargs={"project_id": project.id, "batch_id": batch.id},
        )

    return redirect(redirect_url)


@login_required
def reference_batch_delete(request, project_id, batch_id):
    project = get_object_or_404(Project, pk=project_id)
    batch = get_object_or_404(ReferenceSourceBatch, pk=batch_id, project=project)

    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])

    if not _user_can_edit_project(request.user, project):
        raise PermissionDenied

    label_fragment = batch.label[:80]
    batch.delete()

    messages.success(
        request,
        f"Deleted '{label_fragment}' and its imported references.",
    )

    return redirect(
        "synopsis:reference_batch_list",
        project_id=project.id,
    )


@login_required
def reference_batch_upload(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if request.method == "POST":
        form = ReferenceBatchUploadForm(request.POST, request.FILES)
        if form.is_valid():
            uploaded_file = form.cleaned_data["ris_file"]
            raw_bytes = uploaded_file.read()
            if not raw_bytes.strip():
                form.add_error("ris_file", "The uploaded file appears to be empty.")
            else:
                sha1 = hashlib.sha1(raw_bytes).hexdigest()
                text_payload = raw_bytes.decode("utf-8", errors="ignore")
                records = []
                ris_error = None
                try:
                    records = rispy.loads(text_payload)
                except Exception as exc:  # pragma: no cover - parser errors
                    ris_error = exc

                if not records:
                    plaintext_records = _parse_plaintext_references(text_payload)
                    if plaintext_records:
                        records = plaintext_records
                    elif ris_error:
                        form.add_error(
                            "ris_file",
                            f"Could not parse RIS content ({ris_error}).",
                        )
                    else:
                        form.add_error(
                            "ris_file",
                            "No references were detected. Upload a RIS file or a plain text file where each entry is separated by a blank line.",
                        )

                if records:
                    with transaction.atomic():
                        batch = ReferenceSourceBatch.objects.create(
                            project=project,
                            label=form.cleaned_data["label"],
                            source_type=form.cleaned_data["source_type"],
                            search_date_start=form.cleaned_data.get(
                                "search_date_start"
                            ),
                            search_date_end=form.cleaned_data.get(
                                "search_date_end"
                            ),
                            uploaded_by=request.user,
                            original_filename=getattr(uploaded_file, "name", ""),
                            record_count=0,
                            ris_sha1=sha1,
                            notes=form.cleaned_data.get("notes", ""),
                        )
                        imported = 0
                        duplicates = 0
                        for record in records:
                            title = (
                                _extract_reference_field(record, "primary_title")
                                or _extract_reference_field(record, "title")
                                or _extract_reference_field(
                                    record, "secondary_title"
                                )
                            )
                            if not title:
                                duplicates += 1
                                continue

                            authors_list = (
                                record.get("authors") or record.get("author") or []
                            )
                            if isinstance(authors_list, str):
                                authors_list = [authors_list]
                            authors = "; ".join(str(a) for a in authors_list if a)

                            year = _extract_reference_field(
                                record, "year"
                            ) or _extract_reference_field(
                                record, "publication_year"
                            )
                            doi = _extract_reference_field(record, "doi")
                            hash_key = reference_hash(title, year, doi)

                            if Reference.objects.filter(
                                project=project, hash_key=hash_key
                            ).exists():
                                duplicates += 1
                                continue

                            Reference.objects.create(
                                project=project,
                                batch=batch,
                                hash_key=hash_key,
                                source_identifier=_extract_reference_field(
                                    record, "accession_number"
                                )
                                or _extract_reference_field(record, "id"),
                                title=title,
                                abstract=_extract_reference_field(record, "abstract"),
                                authors=authors,
                                publication_year=_coerce_year(year),
                                journal=_extract_reference_field(
                                    record, "journal_name"
                                )
                                or _extract_reference_field(
                                    record, "secondary_title"
                                ),
                                volume=_extract_reference_field(record, "volume"),
                                issue=_extract_reference_field(record, "issue"),
                                pages=_combine_pages(record),
                                doi=doi,
                                url=_extract_reference_field(record, "url"),
                                language=_extract_reference_field(
                                    record, "language"
                                ),
                                raw_ris=record,
                            )
                            imported += 1

                        batch.record_count = imported
                        batch.save(update_fields=["record_count", "notes"])

                    messages.success(
                        request,
                        f"Imported {imported} reference(s) into '{batch.label}'.",
                    )
                    if duplicates:
                        messages.info(
                            request,
                            f"Skipped {duplicates} record(s) already present in this project.",
                        )
                    return redirect(
                        "synopsis:reference_batch_list", project_id=project.id
                    )
    else:
        form = ReferenceBatchUploadForm()

    return render(
        request,
        "synopsis/reference_batch_upload.html",
        {"project": project, "form": form},
    )


@login_required
def advisory_protocol_feedback_close(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    proto = getattr(project, "protocol", None)
    if not proto:
        messages.error(request, "No protocol configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    action = request.POST.get("action")
    if action == "reopen":
        if request.method != "POST":
            return HttpResponseBadRequest("POST required")
        proto.feedback_closed_at = None
        proto.feedback_closure_message = ""
        proto.save(update_fields=["feedback_closed_at", "feedback_closure_message"])
        _log_project_change(
            project,
            request.user,
            "Protocol feedback reopened",
        )
        messages.success(request, "Protocol feedback reopened for advisory members.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = ProtocolFeedbackCloseForm(request.POST)
    if not form.is_valid():
        context = _advisory_board_context(
            project,
            user=request.user,
            feedback_close_form=form,
        )
        return render(request, "synopsis/advisory_board_list.html", context)

    message = form.cleaned_data.get("message", "")
    now = timezone.now()
    already_closed = proto.feedback_closed_at is not None
    proto.feedback_closed_at = proto.feedback_closed_at or now
    proto.feedback_closure_message = message
    update_fields = ["feedback_closure_message"]
    if not already_closed:
        update_fields.append("feedback_closed_at")
    proto.save(update_fields=update_fields)

    ended_session = _end_active_collaborative_session(
        project,
        CollaborativeSession.DOCUMENT_PROTOCOL,
        ended_by=request.user if getattr(request.user, "is_authenticated", False) else None,
        reason="Protocol feedback window closed",
    )

    if already_closed:
        _log_project_change(
            project,
            request.user,
            "Protocol feedback closure message updated",
            message,
        )
        messages.info(request, "Closure message updated.")
    else:
        _log_project_change(
            project,
            request.user,
            "Protocol feedback closed",
            message,
        )
        messages.success(request, "Protocol feedback links are now closed.")

    if ended_session:
        _log_project_change(
            project,
            request.user,
            "Protocol collaborative session closed",
            f"Session {ended_session.token} marked inactive.",
        )
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_action_list_feedback_close(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.error(request, "No action list configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    action = request.POST.get("action")
    if action == "reopen":
        if request.method != "POST":
            return HttpResponseBadRequest("POST required")
        action_list.feedback_closed_at = None
        action_list.feedback_closure_message = ""
        action_list.save(
            update_fields=["feedback_closed_at", "feedback_closure_message"]
        )
        _log_project_change(
            project,
            request.user,
            "Action list feedback reopened",
        )
        messages.success(request, "Action list feedback reopened for advisory members.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = ActionListFeedbackCloseForm(request.POST)
    if not form.is_valid():
        context = _advisory_board_context(
            project,
            user=request.user,
            action_list_feedback_close_form=form,
        )
        return render(request, "synopsis/advisory_board_list.html", context)

    message = form.cleaned_data.get("message", "")
    now = timezone.now()
    already_closed = action_list.feedback_closed_at is not None
    action_list.feedback_closed_at = action_list.feedback_closed_at or now
    action_list.feedback_closure_message = message
    update_fields = ["feedback_closure_message"]
    if not already_closed:
        update_fields.append("feedback_closed_at")
    action_list.save(update_fields=update_fields)

    ended_session = _end_active_collaborative_session(
        project,
        CollaborativeSession.DOCUMENT_ACTION_LIST,
        ended_by=request.user if getattr(request.user, "is_authenticated", False) else None,
        reason="Action list feedback window closed",
    )

    if already_closed:
        _log_project_change(
            project,
            request.user,
            "Action list feedback closure message updated",
            message,
        )
        messages.info(request, "Closure message updated.")
    else:
        _log_project_change(
            project,
            request.user,
            "Action list feedback closed",
            message,
        )
        messages.success(request, "Action list feedback links are now closed.")

    if ended_session:
        _log_project_change(
            project,
            request.user,
            "Action list collaborative session closed",
            f"Session {ended_session.token} marked inactive.",
        )
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_invite_create(request, project_id, member_id=None):
    """
    Invite by email. If member_id is provided, the invite links to that member
    and updates their invite flags; otherwise the invite appears in the
    “Invited directly” section.
    """
    project = get_object_or_404(Project, pk=project_id)
    initial = {}
    member = None

    action_list = getattr(project, "action_list", None)
    action_document_available = bool(action_list and getattr(action_list, "document", None))
    collaborative_available = bool(_onlyoffice_enabled() and action_document_available)

    if member_id:
        member = get_object_or_404(AdvisoryBoardMember, pk=member_id, project=project)
        initial["email"] = member.email
        if member.response_date:
            initial["due_date"] = member.response_date

    form = None
    if request.method == "POST":
        form = AdvisoryInviteForm(request.POST)
    else:
        form = AdvisoryInviteForm(initial=initial)

    # Adjust optional resources availability before validation so disabled fields
    # behave consistently for both GET and POST.
    if not action_document_available:
        form.fields["include_action_list"].disabled = True
        form.fields["include_action_list"].help_text = "Upload an action list document to include it here."
        form.fields["include_action_list"].initial = False
    else:
        form.fields["include_action_list"].help_text = "Adds a link to the latest action list file."

    if not collaborative_available:
        form.fields["include_collaborative_link"].disabled = True
        form.fields["include_collaborative_link"].help_text = "Enable the collaborative editor or upload the action list to share this link."
        form.fields["include_collaborative_link"].initial = False
    else:
        form.fields["include_collaborative_link"].help_text = "Shares the live collaborative editor for the action list."

    if request.method == "POST" and form.is_valid():
            email = form.cleaned_data["email"].strip()
            due_date = form.cleaned_data.get("due_date")
            message_body = form.cleaned_data.get("message") or ""

            inv = AdvisoryBoardInvitation.objects.create(
                project=project,
                member=member,
                email=email,
                invited_by=request.user,
                due_date=due_date,
            )

            yes_url = request.build_absolute_uri(
                reverse("synopsis:advisory_invite_reply", args=[str(inv.token), "yes"])
            )
            no_url = request.build_absolute_uri(
                reverse("synopsis:advisory_invite_reply", args=[str(inv.token), "no"])
            )
            due_txt = due_date.strftime("%d %b %Y") if due_date else "—"

            subject = email_subject("invite", project, due_date)
            text = (
                f"Hello,\n\n"
                f"You've been invited to advise on '{project.title}'.\n"
                f"Please reply by: {due_txt}\n\n"
                f"Yes: {yes_url}\nNo:  {no_url}\n\n"
                "After clicking Yes you'll be asked to confirm you can actively participate and provide valuable input.\n\n"
                f"{message_body}\n"
            )
            html = (
                f"<p>Hello,</p>"
                f"<p>You've been invited to advise on '<strong>{project.title}</strong>'.</p>"
                f"<p><strong>Please reply by: {due_txt}</strong></p>"
                f"<p>"
                f"<a href='{yes_url}' style='padding:8px 12px;border:1px solid #0a0;text-decoration:none;'>Yes</a> "
                f"<a href='{no_url}' style='padding:8px 12px;border:1px solid #a00;text-decoration:none;margin-left:8px;'>No</a>"
                f"</p>"
                f"<p class='mt-2'><em>After clicking Yes you'll confirm that you will actively participate and provide valuable input.</em></p>"
                f"<p>{message_body}</p>"
            )

            # Collect optional attachments/links
            attachment_lines = []

            include_action_list = (
                action_document_available
                and form.cleaned_data.get("include_action_list")
                and action_list
                and getattr(action_list, "document", None)
            )
            if include_action_list:
                action_url = request.build_absolute_uri(action_list.document.url)
                attachment_lines.append(("Action list", action_url))

            include_collaborative_link = (
                collaborative_available
                and form.cleaned_data.get("include_collaborative_link")
            )
            if include_collaborative_link:
                collab_url = _ensure_collaborative_invite_link(
                    request,
                    project,
                    CollaborativeSession.DOCUMENT_ACTION_LIST,
                    member=member,
                )
                if collab_url:
                    attachment_lines.append(("Collaborative editor", collab_url))

            if attachment_lines:
                text += "\n" + "\n".join(f"{label}: {url}" for label, url in attachment_lines) + "\n"
                for label, url in attachment_lines:
                    html += f"<p><strong>{label}:</strong> <a href='{url}'>{url}</a></p>"

            msg = EmailMultiAlternatives(
                subject,
                text,
                to=[email],
                reply_to=reply_to_list(getattr(request.user, "email", None)),
            )
            msg.attach_alternative(html, "text/html")
            msg.send()

            if member:
                member.invite_sent = True
                member.invite_sent_at = timezone.now()
                update_fields = {"invite_sent", "invite_sent_at"}
                if due_date and member.response_date != due_date:
                    member.response_date = due_date
                    member.reminder_sent = False
                    member.reminder_sent_at = None
                    update_fields.update(
                        {"response_date", "reminder_sent", "reminder_sent_at"}
                    )
                member.save(update_fields=list(update_fields))

            messages.success(request, f"Invitation sent to {email}.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        pass

    return render(
        request,
        "synopsis/advisory_invite_form.html",
        {
            "project": project,
            "form": form,
            "member": member,
            "action_list_available": action_document_available,
            "collaborative_available": collaborative_available,
        },
    )


@csrf_exempt
def advisory_invite_accept(request, token):
    """
    Kept for compatibility with older links that only had 'accept'.
    New invites should use Yes/No links via advisory_invite_reply.
    """
    inv = get_object_or_404(AdvisoryBoardInvitation, token=token)
    if inv.accepted is not True:
        inv.accepted = True
        inv.responded_at = timezone.now()
        inv.save(update_fields=["accepted", "responded_at"])

        if inv.member:
            member = inv.member
            member.response_date = timezone.localdate()
            member.response = "Y"
            member.participation_confirmed = True
            member.participation_confirmed_at = timezone.now()
            if not member.participation_statement:
                member.participation_statement = (
                    "Confirmed participation via legacy link"
                )
            member.save(
                update_fields=[
                    "response_date",
                    "response",
                    "participation_confirmed",
                    "participation_confirmed_at",
                    "participation_statement",
                ]
            )

    return render(
        request,
        "synopsis/advisory_invite_accept.html",
        {"project": inv.project, "invitation": inv},
    )


def advisory_invite_reply(request, token, choice):
    """
    Public Yes/No link handler from the email.
    - If the invite is tied to a member, update that row.
    - If it’s an email-only invite and they click Yes, create a member.
    """
    inv = get_object_or_404(AdvisoryBoardInvitation, token=token)
    choice = (choice or "").lower()
    if choice not in ("yes", "no"):
        return HttpResponseBadRequest("Invalid choice")

    accepted = choice == "yes"
    member = inv.member

    if accepted:
        if member and member.participation_confirmed:
            if not inv.accepted:
                inv.accepted = True
                inv.responded_at = timezone.now()
                inv.save(update_fields=["accepted", "responded_at"])
            return render(
                request,
                "synopsis/invite_thanks.html",
                {"member": member, "project": inv.project, "accepted": True},
            )

        form = ParticipationConfirmForm(request.POST or None)
        if request.method == "POST":
            if form.is_valid():
                statement = (form.cleaned_data.get("statement") or "").strip()
                if not statement:
                    statement = "Participation confirmed"
                now = timezone.now()
                today = timezone.localdate()

                if member is None:
                    member = AdvisoryBoardMember.objects.create(
                        project=inv.project,
                        email=inv.email,
                        first_name="",
                        last_name="",
                        organisation="",
                    )
                    inv.member = member

                updates = set()
                if member.response != "Y":
                    member.response = "Y"
                    updates.add("response")
                if not member.response_date:
                    member.response_date = today
                    updates.add("response_date")
                member.participation_confirmed = True
                member.participation_confirmed_at = now
                member.participation_statement = statement
                updates.update(
                    {
                        "participation_confirmed",
                        "participation_confirmed_at",
                        "participation_statement",
                    }
                )
                member.save(update_fields=list(updates))

                inv.accepted = True
                inv.responded_at = now
                inv.save(update_fields=["accepted", "responded_at", "member"])

                return render(
                    request,
                    "synopsis/invite_thanks.html",
                    {
                        "member": member,
                        "project": inv.project,
                        "accepted": inv.accepted,
                    },
                )

        return render(
            request,
            "synopsis/advisory_participation_confirm.html",
            {
                "project": inv.project,
                "invitation": inv,
                "member": member,
                "form": form,
            },
        )

    decline_form = ParticipationDeclineForm(request.POST or None)

    if request.method == "POST" and decline_form.is_valid():
        reason = (decline_form.cleaned_data.get("reason") or "").strip()
        if member:
            updates = {
                "response",
                "response_date",
                "participation_confirmed",
                "participation_confirmed_at",
                "participation_statement",
            }
            member.response = "N"
            member.response_date = timezone.localdate()
            member.participation_confirmed = False
            member.participation_confirmed_at = None
            member.participation_statement = reason
            member.save(update_fields=list(updates))

        inv.accepted = False
        inv.responded_at = timezone.now()
        inv.save(update_fields=["accepted", "responded_at", "member"] if member else ["accepted", "responded_at"])

        return render(
            request,
            "synopsis/invite_thanks.html",
            {"member": member, "project": inv.project, "accepted": inv.accepted},
        )

    return render(
        request,
        "synopsis/advisory_participation_decline.html",
        {
            "project": inv.project,
            "invitation": inv,
            "member": member,
            "form": decline_form,
        },
    )


@login_required
def advisory_invite_update_due_date(request, project_id, invitation_id):
    project = get_object_or_404(Project, pk=project_id)
    inv = get_object_or_404(AdvisoryBoardInvitation, pk=invitation_id, project=project)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    date_str = (request.POST.get("due_date") or "").strip()
    inv.due_date = dt.date.fromisoformat(date_str) if date_str else None
    inv.save(update_fields=["due_date"])
    messages.success(request, f"Response date updated for {inv.email}.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def send_advisory_invites(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    ids = request.POST.getlist("member_ids")
    members = AdvisoryBoardMember.objects.filter(project=project, id__in=ids)

    for m in members:
        inv = AdvisoryBoardInvitation.objects.create(
            project=project,
            member=m,
            email=m.email,
            invited_by=request.user,
            due_date=m.response_date,
        )
        yes_url = request.build_absolute_uri(
            reverse("synopsis:advisory_invite_reply", args=[inv.token, "yes"])
        )
        no_url = request.build_absolute_uri(
            reverse("synopsis:advisory_invite_reply", args=[inv.token, "no"])
        )
        deadline_txt = m.response_date.strftime("%d %b %Y") if m.response_date else "—"

        subject = email_subject("invite", project, m.response_date)
        text = (
            f"Dear {m.first_name},\n\n"
            f"You are invited to advise on '{project.title}'.\n"
            f"Please reply by: {deadline_txt}\n\n"
            f"Yes: {yes_url}\nNo:  {no_url}\n\n"
            "After clicking Yes you'll be asked to confirm you can actively participate and provide valuable input.\n\n"
            f"Thank you."
        )
        html = (
            f"<p>Dear {m.first_name},</p>"
            f"<p>You are invited to advise on '<strong>{project.title}</strong>'.</p>"
            f"<p><strong>Please reply by: {deadline_txt}</strong></p>"
            f"<p>"
            f"<a href='{yes_url}' style='padding:8px 12px;border:1px solid #0a0;text-decoration:none;'>Yes</a> "
            f"<a href='{no_url}' style='padding:8px 12px;border:1px solid #a00;text-decoration:none;margin-left:8px;'>No</a>"
            f"</p>"
            "<p><em>After clicking Yes you'll confirm that you will actively participate and provide valuable input.</em></p>"
        )

        msg = EmailMultiAlternatives(
            subject,
            text,
            to=[m.email],
            reply_to=reply_to_list(getattr(request.user, "email", None)),
        )
        msg.attach_alternative(html, "text/html")
        msg.send()

        m.invite_sent = True
        m.invite_sent_at = timezone.now()
        m.save(update_fields=["invite_sent", "invite_sent_at"])

    messages.success(request, f"Sent {members.count()} invite(s).")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_send_invites_bulk(request, project_id):
    """Compose and send invitations to all members with an email."""
    project = get_object_or_404(Project, id=project_id)

    action_list = getattr(project, "action_list", None)
    action_document_available = bool(action_list and getattr(action_list, "document", None))
    collaborative_available = bool(_onlyoffice_enabled() and action_document_available)

    if request.method == "POST":
        form = AdvisoryBulkInviteForm(request.POST)
    else:
        form = AdvisoryBulkInviteForm()

    if not action_document_available:
        form.fields["include_action_list"].disabled = True
        form.fields["include_action_list"].help_text = "Upload an action list document to include it here."
        form.fields["include_action_list"].initial = False
    else:
        form.fields["include_action_list"].help_text = "Adds a link to the latest action list file."

    if not collaborative_available:
        form.fields["include_collaborative_link"].disabled = True
        form.fields["include_collaborative_link"].help_text = "Enable the collaborative editor and upload the action list to share this link."
        form.fields["include_collaborative_link"].initial = False
    else:
        form.fields["include_collaborative_link"].help_text = "Shares the live collaborative editor for the action list."

    if request.method == "POST" and form.is_valid():
        members = (
            AdvisoryBoardMember.objects.filter(project=project, invite_sent=False)
            .exclude(email__isnull=True)
            .exclude(email__exact="")
        )
        if not members:
            messages.info(
                request,
                "All current members have already received an invitation. Add new members before using this bulk send.",
            )
            return redirect("synopsis:advisory_board_list", project_id=project.id)

        message_body = form.cleaned_data.get("message") or ""
        bulk_due_date = form.cleaned_data.get("due_date")

        include_action_list = action_document_available and form.cleaned_data.get("include_action_list")
        include_collaborative_link = (
            collaborative_available and form.cleaned_data.get("include_collaborative_link")
        )

        action_url = (
            request.build_absolute_uri(action_list.document.url)
            if include_action_list and action_list and getattr(action_list, "document", None)
            else ""
        )

        sent = 0
        for member in members:
            due_date = bulk_due_date or member.response_date
            inv = AdvisoryBoardInvitation.objects.create(
                project=project,
                member=member,
                email=member.email,
                invited_by=request.user,
                due_date=due_date,
            )

            yes_url = request.build_absolute_uri(
                reverse("synopsis:advisory_invite_reply", args=[inv.token, "yes"])
            )
            no_url = request.build_absolute_uri(
                reverse("synopsis:advisory_invite_reply", args=[inv.token, "no"])
            )
            deadline_txt = due_date.strftime("%d %b %Y") if due_date else "—"

            subject = email_subject("invite", project, due_date)
            text = (
                f"Dear {member.first_name or 'colleague'},\n\n"
                f"You are invited to advise on '{project.title}'.\n"
                f"Please reply by: {deadline_txt}\n\n"
                f"Yes: {yes_url}\nNo:  {no_url}\n\n"
                "After clicking Yes you'll be asked to confirm you can actively participate and provide valuable input.\n\n"
                f"{message_body}\n"
            )
            html = (
                f"<p>Dear {member.first_name or 'colleague'},</p>"
                f"<p>You are invited to advise on '<strong>{project.title}</strong>'.</p>"
                f"<p><strong>Please reply by: {deadline_txt}</strong></p>"
                f"<p>"
                f"<a href='{yes_url}' style='padding:8px 12px;border:1px solid #0a0;text-decoration:none;'>Yes</a> "
                f"<a href='{no_url}' style='padding:8px 12px;border:1px solid #a00;text-decoration:none;margin-left:8px;'>No</a>"
                f"</p>"
                f"<p>{message_body}</p>"
                "<p><em>After clicking Yes you'll confirm that you will actively participate and provide valuable input.</em></p>"
            )

            attachment_lines = []
            if action_url:
                attachment_lines.append(("Action list", action_url))

            collab_url = ""
            if include_collaborative_link:
                collab_url = _ensure_collaborative_invite_link(
                    request,
                    project,
                    CollaborativeSession.DOCUMENT_ACTION_LIST,
                    member=member,
                )
                if collab_url:
                    attachment_lines.append(("Collaborative editor", collab_url))

            if attachment_lines:
                text += "\n" + "\n".join(f"{label}: {url}" for label, url in attachment_lines) + "\n"
                for label, url in attachment_lines:
                    html += f"<p><strong>{label}:</strong> <a href='{url}'>{url}</a></p>"

            msg = EmailMultiAlternatives(
                subject,
                text,
                to=[member.email],
                reply_to=reply_to_list(getattr(request.user, "email", None)),
            )
            msg.attach_alternative(html, "text/html")
            inviter_email = getattr(request.user, "email", None)
            if inviter_email:
                msg.extra_headers = msg.extra_headers or {}
                msg.extra_headers["List-Unsubscribe"] = f"<mailto:{inviter_email}>"
            msg.send()

            member.invite_sent = True
            member.invite_sent_at = timezone.now()
            update_fields = {"invite_sent", "invite_sent_at"}
            if due_date and member.response_date != due_date:
                member.response_date = due_date
                member.reminder_sent = False
                member.reminder_sent_at = None
                update_fields.update({"response_date", "reminder_sent", "reminder_sent_at"})
            member.save(update_fields=list(update_fields))
            sent += 1

        messages.success(request, f"Sent {sent} invite(s).")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    return render(
        request,
        "synopsis/advisory_invite_compose_all.html",
        {
            "project": project,
            "form": form,
            "action_list_available": action_document_available,
            "collaborative_available": collaborative_available,
        },
    )


@login_required
def send_protocol(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not hasattr(project, "protocol"):
        messages.error(request, "No protocol uploaded for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    ids = request.POST.getlist("member_ids")
    members = AdvisoryBoardMember.objects.filter(project=project, id__in=ids)

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = email_subject("protocol_review", project)
    for m in members:
        text = (
            f"Dear {m.first_name or 'colleague'},\n\n"
            f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
            f"Deadline for protocol feedback: "
            f"{_format_deadline(m.feedback_on_protocol_deadline)}\n"
        )
        msg = EmailMultiAlternatives(
            subject,
            text,
            to=[m.email],
            reply_to=reply_to_list(getattr(request.user, "email", None)),
        )
        msg.send()
        m.sent_protocol_at = timezone.now()
        m.protocol_reminder_sent = False
        m.protocol_reminder_sent_at = None
        m.save(
            update_fields=[
                "sent_protocol_at",
                "protocol_reminder_sent",
                "protocol_reminder_sent_at",
            ]
        )

    messages.success(request, f"Sent protocol to {members.count()} member(s).")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_send_protocol_bulk(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not hasattr(project, "protocol"):
        messages.error(request, "No protocol uploaded for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    members = (
        AdvisoryBoardMember.objects.filter(
            project=project,
            response="Y",
            participation_confirmed=True,
        )
        .exclude(email__isnull=True)
        .exclude(email__exact="")
    )
    if not members:
        messages.info(
            request,
            "No eligible members found. Only members who accepted and confirmed participation can receive the protocol.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = email_subject("protocol_review", project)

    sent = 0
    for m in members:
        text = (
            f"Dear {m.first_name or 'colleague'},\n\n"
            f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
            f"Deadline for protocol feedback: "
            f"{_format_deadline(m.feedback_on_protocol_deadline)}\n"
        )
        msg = EmailMultiAlternatives(
            subject,
            text,
            to=[m.email],
            reply_to=reply_to_list(getattr(request.user, "email", None)),
        )
        msg.send()
        m.sent_protocol_at = timezone.now()
        m.protocol_reminder_sent = False
        m.protocol_reminder_sent_at = None
        m.save(
            update_fields=[
                "sent_protocol_at",
                "protocol_reminder_sent",
                "protocol_reminder_sent_at",
            ]
        )
        sent += 1

    messages.success(request, f"Sent protocol to {sent} member(s).")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_send_protocol_member(request, project_id, member_id):
    project = get_object_or_404(Project, id=project_id)
    if not hasattr(project, "protocol"):
        messages.error(request, "No protocol uploaded for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    m = get_object_or_404(AdvisoryBoardMember, id=member_id, project=project)
    if not m.email:
        messages.error(request, "This member has no email.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    if m.response != "Y" or not m.participation_confirmed:
        messages.error(
            request,
            "This member has not accepted the invitation or has declined participation.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = email_subject("protocol_review", project)
    deadline_text = _format_deadline(m.feedback_on_protocol_deadline)
    fb = _create_protocol_feedback(project, member=m, email=m.email)
    feedback_url = request.build_absolute_uri(
        reverse("synopsis:protocol_feedback", args=[str(fb.token)])
    )

    text = (
        f"Dear {m.first_name or 'colleague'},\n\n"
        f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
        f"Deadline for protocol feedback: {deadline_text}\n"
        f"Provide feedback: {feedback_url}\n"
    )

    collaborative_url = ""
    protocol_closed = bool(getattr(project.protocol, "feedback_closed_at", None))
    if (
        _onlyoffice_enabled()
        and _document_requires_file(project.protocol)
        and not protocol_closed
    ):
        collaborative_url = _ensure_collaborative_invite_link(
            request,
            project,
            CollaborativeSession.DOCUMENT_PROTOCOL,
            None,
            member=m,
            feedback=fb,
        )
        if collaborative_url:
            text += f"Collaborative editor: {collaborative_url}\n"

    msg = EmailMultiAlternatives(
        subject,
        text,
        to=[m.email],
        reply_to=reply_to_list(getattr(request.user, "email", None)),
    )
    html = (
        f"<p>Dear {m.first_name or 'colleague'},</p>"
        f"<p>Please review the protocol for '<strong>{project.title}</strong>': "
        f"<a href='{proto_url}'>View document</a></p>"
        f"<p>Deadline for protocol feedback: {deadline_text}</p>"
        f"<p><a href='{feedback_url}'>Provide feedback</a></p>"
    )
    if collaborative_url:
        html += (
            "<p><strong>Collaborative editor:</strong> "
            f"<a href='{collaborative_url}'>Open live editor</a></p>"
        )
    msg.attach_alternative(html, "text/html")
    msg.send()

    m.sent_protocol_at = timezone.now()
    m.protocol_reminder_sent = False
    m.protocol_reminder_sent_at = None
    m.save(
        update_fields=[
            "sent_protocol_at",
            "protocol_reminder_sent",
            "protocol_reminder_sent_at",
        ]
    )

    messages.success(request, f"Sent protocol to {m.email}.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_send_protocol_compose_all(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    proto = getattr(project, "protocol", None)
    if not proto:
        messages.error(request, "No protocol configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    protocol_closed = bool(getattr(proto, "feedback_closed_at", None))
    collaborative_enabled = (
        _onlyoffice_enabled()
        and _document_requires_file(proto)
        and not protocol_closed
    )
    if request.method == "POST":
        form = ProtocolSendForm(
            request.POST, collaborative_enabled=collaborative_enabled
        )
        if form.is_valid():
            members = (
                AdvisoryBoardMember.objects.filter(
                    project=project,
                    response="Y",
                    participation_confirmed=True,
                )
                .exclude(email__isnull=True)
                .exclude(email__exact="")
            )
            if not members:
                messages.info(
                    request,
                    "No eligible members found. Only members who accepted and confirmed participation can receive the protocol.",
                )
                return redirect("synopsis:advisory_board_list", project_id=project.id)
            content = form.cleaned_data["content"]
            message_body = form.cleaned_data.get("message") or ""
            include_collab = collaborative_enabled and form.cleaned_data.get(
                "include_collaborative_link"
            )
            sent = 0
            for m in members:
                fb = _create_protocol_feedback(project, member=m, email=m.email)
                feedback_url = request.build_absolute_uri(
                    reverse("synopsis:protocol_feedback", args=[str(fb.token)])
                )
                subject = email_subject("protocol_review", project)
                text = f"Dear {m.first_name or 'colleague'},\n\n{message_body}\n\n"
                html = (
                    f"<p>Dear {m.first_name or 'colleague'},</p>"
                    f"<p>{message_body}</p>"
                )
                if content == "file" and getattr(proto, "document", None):
                    proto_url = request.build_absolute_uri(proto.document.url)
                    text += f"Please review the protocol: {proto_url}\n\n"
                    html += f"<p>Please review the protocol: <a href='{proto_url}'>View document</a></p>"
                elif content == "text" and (proto.text_version or "").strip():
                    html += "<hr>" + proto.text_version
                text += f"Provide feedback: {feedback_url}\n"
                html += f"<p><a href='{feedback_url}'>Provide feedback</a></p>"
                if include_collab:
                    collaborative_url = _ensure_collaborative_invite_link(
                        request,
                        project,
                        CollaborativeSession.DOCUMENT_PROTOCOL,
                        None,
                        member=m,
                        feedback=fb,
                    )
                    if collaborative_url:
                        text += f"Collaborative editor: {collaborative_url}\n"
                        html += (
                            "<p><strong>Collaborative editor:</strong> "
                            f"<a href='{collaborative_url}'>Open live editor</a></p>"
                        )

                msg = EmailMultiAlternatives(
                    subject,
                    text,
                    to=[m.email],
                    reply_to=reply_to_list(getattr(request.user, "email", None)),
                )
                msg.attach_alternative(html, "text/html")
                inviter_email = getattr(request.user, "email", None)
                if inviter_email:
                    msg.extra_headers = msg.extra_headers or {}
                    msg.extra_headers["List-Unsubscribe"] = f"<mailto:{inviter_email}>"
                msg.send()
                m.sent_protocol_at = timezone.now()
                m.protocol_reminder_sent = False
                m.protocol_reminder_sent_at = None
                m.save(
                    update_fields=[
                        "sent_protocol_at",
                        "protocol_reminder_sent",
                        "protocol_reminder_sent_at",
                    ]
                )
                sent += 1
            messages.success(request, f"Sent protocol to {sent} member(s).")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = ProtocolSendForm(
            initial={
                "content": "file",
                "include_collaborative_link": collaborative_enabled,
            },
            collaborative_enabled=collaborative_enabled,
        )
    return render(
        request,
        "synopsis/protocol_send_compose.html",
        {"project": project, "form": form, "scope": "all"},
    )


@login_required
def advisory_send_protocol_compose_member(request, project_id, member_id):
    project = get_object_or_404(Project, id=project_id)
    proto = getattr(project, "protocol", None)
    if not proto:
        messages.error(request, "No protocol configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    m = get_object_or_404(AdvisoryBoardMember, id=member_id, project=project)
    if m.response != "Y" or not m.participation_confirmed:
        messages.error(
            request,
            "This member has not accepted the invitation or has declined participation.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    protocol_closed = bool(getattr(proto, "feedback_closed_at", None))
    collaborative_enabled = (
        _onlyoffice_enabled()
        and _document_requires_file(proto)
        and not protocol_closed
    )
    if request.method == "POST":
        form = ProtocolSendForm(
            request.POST, collaborative_enabled=collaborative_enabled
        )
        if form.is_valid():
            content = form.cleaned_data["content"]
            message_body = form.cleaned_data.get("message") or ""
            fb = _create_protocol_feedback(project, member=m, email=m.email)
            feedback_url = request.build_absolute_uri(
                reverse("synopsis:protocol_feedback", args=[str(fb.token)])
            )
            subject = email_subject("protocol_review", project)
            text = f"Dear {m.first_name or 'colleague'},\n\n{message_body}\n\n"
            html = (
                f"<p>Dear {m.first_name or 'colleague'},</p>" f"<p>{message_body}</p>"
            )
            if content == "file" and getattr(proto, "document", None):
                proto_url = request.build_absolute_uri(proto.document.url)
                text += f"Please review the protocol: {proto_url}\n\n"
                html += f"<p>Please review the protocol: <a href='{proto_url}'>View document</a></p>"
            elif content == "text" and (proto.text_version or "").strip():
                html += "<hr>" + proto.text_version
            text += f"Provide feedback: {feedback_url}\n"
            html += f"<p><a href='{feedback_url}'>Provide feedback</a></p>"
            if collaborative_enabled and form.cleaned_data.get(
                "include_collaborative_link"
            ):
                collaborative_url = _ensure_collaborative_invite_link(
                    request,
                    project,
                    CollaborativeSession.DOCUMENT_PROTOCOL,
                    None,
                    member=m,
                    feedback=fb,
                )
                if collaborative_url:
                    text += f"Collaborative editor: {collaborative_url}\n"
                    html += (
                        "<p><strong>Collaborative editor:</strong> "
                        f"<a href='{collaborative_url}'>Open live editor</a></p>"
                    )

            msg = EmailMultiAlternatives(
                subject,
                text,
                to=[m.email],
                reply_to=reply_to_list(getattr(request.user, "email", None)),
            )
            msg.attach_alternative(html, "text/html")
            msg.send()

            m.sent_protocol_at = timezone.now()
            m.protocol_reminder_sent = False
            m.protocol_reminder_sent_at = None
            m.save(
                update_fields=[
                    "sent_protocol_at",
                    "protocol_reminder_sent",
                    "protocol_reminder_sent_at",
                ]
            )
            messages.success(request, f"Sent protocol to {m.email}.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = ProtocolSendForm(
            initial={
                "content": "file",
                "include_collaborative_link": collaborative_enabled,
            },
            collaborative_enabled=collaborative_enabled,
        )
    return render(
        request,
        "synopsis/protocol_send_compose.html",
        {"project": project, "form": form, "scope": "member", "member": m},
    )


@login_required
def advisory_send_action_list_compose_all(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.error(request, "No action list configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    action_closed = bool(getattr(action_list, "feedback_closed_at", None))
    collaborative_enabled = (
        _onlyoffice_enabled()
        and _document_requires_file(action_list)
        and not action_closed
    )
    if request.method == "POST":
        form = ActionListSendForm(
            request.POST, collaborative_enabled=collaborative_enabled
        )
        if form.is_valid():
            members = (
                AdvisoryBoardMember.objects.filter(
                    project=project,
                    response="Y",
                    participation_confirmed=True,
                )
                .exclude(email__isnull=True)
                .exclude(email__exact="")
            )
            if not members:
                messages.info(
                    request,
                    "No eligible members found. Only members who accepted and confirmed participation can receive the action list.",
                )
                return redirect("synopsis:advisory_board_list", project_id=project.id)
            content = form.cleaned_data["content"]
            message_body = form.cleaned_data.get("message") or ""
            include_collab = collaborative_enabled and form.cleaned_data.get(
                "include_collaborative_link"
            )
            sent = 0
            for m in members:
                fb = _create_action_list_feedback(project, member=m, email=m.email)
                feedback_url = request.build_absolute_uri(
                    reverse("synopsis:action_list_feedback", args=[str(fb.token)])
                )
                subject = email_subject("action_list_review", project)
                text = f"Dear {m.first_name or 'colleague'},\n\n{message_body}\n\n"
                html = (
                    f"<p>Dear {m.first_name or 'colleague'},</p>"
                    f"<p>{message_body}</p>"
                )
                if content == "file" and getattr(action_list, "document", None):
                    doc_url = request.build_absolute_uri(action_list.document.url)
                    text += f"Please review the action list: {doc_url}\n\n"
                    html += f"<p>Please review the action list: <a href='{doc_url}'>View document</a></p>"
                elif content == "text" and (action_list.text_version or "").strip():
                    html += "<hr>" + action_list.text_version
                text += f"Provide feedback: {feedback_url}\n"
                html += f"<p><a href='{feedback_url}'>Provide feedback</a></p>"
                if include_collab:
                    collaborative_url = _ensure_collaborative_invite_link(
                        request,
                        project,
                        CollaborativeSession.DOCUMENT_ACTION_LIST,
                        None,
                        member=m,
                        feedback=fb,
                    )
                    if collaborative_url:
                        text += f"Collaborative editor: {collaborative_url}\n"
                        html += (
                            "<p><strong>Collaborative editor:</strong> "
                            f"<a href='{collaborative_url}'>Open live editor</a></p>"
                        )

                msg = EmailMultiAlternatives(
                    subject,
                    text,
                    to=[m.email],
                    reply_to=reply_to_list(getattr(request.user, "email", None)),
                )
                msg.attach_alternative(html, "text/html")
                inviter_email = getattr(request.user, "email", None)
                if inviter_email:
                    msg.extra_headers = msg.extra_headers or {}
                    msg.extra_headers["List-Unsubscribe"] = f"<mailto:{inviter_email}>"
                msg.send()
                m.sent_action_list_at = timezone.now()
                m.action_list_reminder_sent = False
                m.action_list_reminder_sent_at = None
                m.save(
                    update_fields=[
                        "sent_action_list_at",
                        "action_list_reminder_sent",
                        "action_list_reminder_sent_at",
                    ]
                )
                sent += 1
            messages.success(request, f"Sent action list to {sent} member(s).")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = ActionListSendForm(
            initial={
                "content": "file",
                "include_collaborative_link": collaborative_enabled,
            },
            collaborative_enabled=collaborative_enabled,
        )
    return render(
        request,
        "synopsis/action_list_send_compose.html",
        {"project": project, "form": form, "scope": "all"},
    )


@login_required
def advisory_send_action_list_compose_member(request, project_id, member_id):
    project = get_object_or_404(Project, id=project_id)
    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.error(request, "No action list configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    member = get_object_or_404(AdvisoryBoardMember, id=member_id, project=project)
    if not member.email:
        messages.error(request, "This member has no email.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    if member.response != "Y" or not member.participation_confirmed:
        messages.error(
            request,
            "This member has not accepted the invitation or has declined participation.",
        )
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    action_closed = bool(getattr(action_list, "feedback_closed_at", None))
    collaborative_enabled = (
        _onlyoffice_enabled()
        and _document_requires_file(action_list)
        and not action_closed
    )
    if request.method == "POST":
        form = ActionListSendForm(
            request.POST, collaborative_enabled=collaborative_enabled
        )
        if form.is_valid():
            content = form.cleaned_data["content"]
            message_body = form.cleaned_data.get("message") or ""
            fb = _create_action_list_feedback(
                project, member=member, email=member.email
            )
            feedback_url = request.build_absolute_uri(
                reverse("synopsis:action_list_feedback", args=[str(fb.token)])
            )
            subject = email_subject("action_list_review", project)
            text = f"Dear {member.first_name or 'colleague'},\n\n{message_body}\n\n"
            html = (
                f"<p>Dear {member.first_name or 'colleague'},</p>"
                f"<p>{message_body}</p>"
            )
            if content == "file" and getattr(action_list, "document", None):
                doc_url = request.build_absolute_uri(action_list.document.url)
                text += f"Please review the action list: {doc_url}\n\n"
                html += f"<p>Please review the action list: <a href='{doc_url}'>View document</a></p>"
            elif content == "text" and (action_list.text_version or "").strip():
                html += "<hr>" + action_list.text_version
            text += f"Provide feedback: {feedback_url}\n"
            html += f"<p><a href='{feedback_url}'>Provide feedback</a></p>"
            if collaborative_enabled and form.cleaned_data.get(
                "include_collaborative_link"
            ):
                collaborative_url = _ensure_collaborative_invite_link(
                    request,
                    project,
                    CollaborativeSession.DOCUMENT_ACTION_LIST,
                    None,
                    member=member,
                    feedback=fb,
                )
                if collaborative_url:
                    text += f"Collaborative editor: {collaborative_url}\n"
                    html += (
                        "<p><strong>Collaborative editor:</strong> "
                        f"<a href='{collaborative_url}'>Open live editor</a></p>"
                    )

            msg = EmailMultiAlternatives(
                subject,
                text,
                to=[member.email],
                reply_to=reply_to_list(getattr(request.user, "email", None)),
            )
            msg.attach_alternative(html, "text/html")
            msg.send()

            member.sent_action_list_at = timezone.now()
            member.action_list_reminder_sent = False
            member.action_list_reminder_sent_at = None
            member.save(
                update_fields=[
                    "sent_action_list_at",
                    "action_list_reminder_sent",
                    "action_list_reminder_sent_at",
                ]
            )
            messages.success(request, f"Sent action list to {member.email}.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = ActionListSendForm(
            initial={
                "content": "file",
                "include_collaborative_link": collaborative_enabled,
            },
            collaborative_enabled=collaborative_enabled,
        )
    return render(
        request,
        "synopsis/action_list_send_compose.html",
        {
            "project": project,
            "form": form,
            "scope": "member",
            "member": member,
        },
    )


@login_required
def advisory_member_custom_data(request, project_id, member_id):
    project = get_object_or_404(Project, pk=project_id)
    member = get_object_or_404(AdvisoryBoardMember, pk=member_id, project=project)

    if not _user_can_edit_project(request.user, project):
        messages.error(request, "You do not have permission to update this member.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    status_key = _member_section_key(member)
    all_fields = list(
        AdvisoryBoardCustomField.objects.filter(project=project).order_by(
            "display_order", "name", "id"
        )
    )
    applicable_fields = [field for field in all_fields if field.applies_to(status_key)]

    focus_field_id = request.GET.get("field") or request.POST.get("focused_field")
    focused_field = None
    if focus_field_id:
        try:
            focused_field = next(
                field for field in applicable_fields if str(field.id) == str(focus_field_id)
            )
            applicable_fields = [focused_field]
        except StopIteration:
            focused_field = None

    existing_values = {
        value.field_id: value.value
        for value in AdvisoryBoardCustomFieldValue.objects.filter(
            member=member, field__project=project
        )
    }

    if request.method == "POST":
        form = AdvisoryMemberCustomDataForm(
            applicable_fields,
            status_key,
            existing_values,
            request.POST,
            form_id=f"member-form-{member.id}",
        )
        if form.is_valid():
            actor = request.user if getattr(request.user, "is_authenticated", False) else None
            for field in applicable_fields:
                cleaned_value = form.cleaned_value(field)
                field.set_value_for_member(
                    member,
                    cleaned_value,
                    changed_by=actor,
                )
            messages.success(
                request,
                f"Updated custom data for {member.first_name or member.email}.",
            )
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = AdvisoryMemberCustomDataForm(
            applicable_fields, status_key, existing_values
        )

    form.apply_widget_configuration()

    history_map = {}
    if applicable_fields:
        history_qs = (
            AdvisoryBoardCustomFieldValueHistory.objects.filter(
                member=member, field__in=applicable_fields
            )
            .select_related("field", "changed_by")
            .order_by("-created_at", "-id")
        )
        for entry in history_qs:
            bucket = history_map.setdefault(entry.field_id, [])
            if len(bucket) >= 10:
                continue
            bucket.append(entry)

    return render(
        request,
        "synopsis/advisory_member_custom_data.html",
        {
            "project": project,
            "member": member,
            "form": form,
            "fields": applicable_fields,
            "status_key": status_key,
            "history_map": history_map,
            "focused_field": focused_field,
        },
    )


def protocol_feedback(request, token):
    fb = get_object_or_404(ProtocolFeedback, token=token)
    member = fb.member
    project = fb.project
    proto = getattr(project, "protocol", None)

    deadline = fb.feedback_deadline_at
    if member and member.feedback_on_protocol_deadline:
        deadline = member.feedback_on_protocol_deadline
        if fb.feedback_deadline_at != deadline:
            fb.feedback_deadline_at = deadline
            fb.save(update_fields=["feedback_deadline_at"])
    if member and member.response != "Y":
        if fb.feedback_deadline_at:
            fb.feedback_deadline_at = None
            fb.save(update_fields=["feedback_deadline_at"])
        deadline = None
    closure_message = None
    now = timezone.now()

    if member and member.response == "N":
        return render(
            request,
            "synopsis/protocol_feedback_thanks.html",
            {
                "project": project,
                "error": "This link is no longer available because you declined the invitation.",
            },
        )

    if proto and proto.feedback_closed_at:
        closure_message = proto.feedback_closure_message or (
            "The authors have closed feedback for this protocol."
        )
        return render(
            request,
            "synopsis/protocol_feedback_thanks.html",
            {
                "project": project,
                "feedback": fb,
                "closed_message": closure_message,
                "deadline": deadline,
                "closed": True,
            },
        )

    if deadline and now >= deadline:
        closure_message = (
            "The feedback deadline has passed (" f"{_format_deadline(deadline)})."
        )
        return render(
            request,
            "synopsis/protocol_feedback_thanks.html",
            {
                "project": project,
                "feedback": fb,
                "closed_message": closure_message,
                "deadline": deadline,
                "closed": True,
            },
        )

    if request.method == "POST":
        form = ProtocolFeedbackForm(request.POST, request.FILES)
        if form.is_valid():
            content = form.cleaned_data["content"].strip()
            uploaded_doc = form.cleaned_data["uploaded_document"]
            updates = []
            if content:
                fb.content = content
                updates.append("content")
            if uploaded_doc:
                fb.uploaded_document = uploaded_doc
                updates.append("uploaded_document")
            if updates:
                fb.submitted_at = timezone.now()
                updates.append("submitted_at")
                fb.save(update_fields=updates)

                if member:
                    member_updates = set()
                    today = timezone.localdate()
                    if member.feedback_on_protocol_received != today:
                        member.feedback_on_protocol_received = today
                        member_updates.add("feedback_on_protocol_received")
                    if member_updates:
                        member.save(update_fields=list(member_updates))

                details = []
                if uploaded_doc:
                    details.append(
                        f"Document uploaded: {fb.latest_document_label or uploaded_doc.name}"
                    )
                if content:
                    snippet = (content[:97] + "…") if len(content) > 100 else content
                    details.append(f"Comments provided: {snippet}")
                if details:
                    _log_project_change(
                        project,
                        request.user,
                        "Protocol feedback submitted",
                        " | ".join(details),
                    )
            return render(
                request,
                "synopsis/protocol_feedback_thanks.html",
                {
                    "project": project,
                    "feedback": fb,
                    "deadline": deadline,
                },
            )
    else:
        form = ProtocolFeedbackForm(initial={"content": fb.content})

    return render(
        request,
        "synopsis/protocol_feedback_form.html",
        {
            "project": project,
            "token": fb.token,
            "feedback": fb,
            "deadline": deadline,
            "form": form,
        },
    )


def action_list_feedback(request, token):
    fb = get_object_or_404(ActionListFeedback, token=token)
    member = fb.member
    project = fb.project
    action_list = fb.action_list or getattr(project, "action_list", None)

    deadline = fb.feedback_deadline_at
    if member and member.feedback_on_action_list_deadline:
        deadline = member.feedback_on_action_list_deadline
        if fb.feedback_deadline_at != deadline:
            fb.feedback_deadline_at = deadline
            fb.save(update_fields=["feedback_deadline_at"])
    if member and member.response != "Y":
        if fb.feedback_deadline_at:
            fb.feedback_deadline_at = None
            fb.save(update_fields=["feedback_deadline_at"])
        deadline = None
    closure_message = None
    now = timezone.now()

    if member and member.response == "N":
        return render(
            request,
            "synopsis/action_list_feedback_thanks.html",
            {
                "project": project,
                "error": "This link is no longer available because you declined the invitation.",
            },
        )

    if action_list and action_list.feedback_closed_at:
        closure_message = action_list.feedback_closure_message or (
            "The authors have closed feedback for this action list."
        )
        return render(
            request,
            "synopsis/action_list_feedback_thanks.html",
            {
                "project": project,
                "feedback": fb,
                "closed_message": closure_message,
                "deadline": deadline,
                "closed": True,
            },
        )

    if deadline and now >= deadline:
        closure_message = (
            "The feedback deadline has passed (" f"{_format_deadline(deadline)})."
        )
        return render(
            request,
            "synopsis/action_list_feedback_thanks.html",
            {
                "project": project,
                "feedback": fb,
                "closed_message": closure_message,
                "deadline": deadline,
                "closed": True,
            },
        )

    if request.method == "POST":
        form = ActionListFeedbackForm(request.POST, request.FILES)
        if form.is_valid():
            content = form.cleaned_data["content"].strip()
            uploaded_doc = form.cleaned_data["uploaded_document"]
            updates = []
            if content:
                fb.content = content
                updates.append("content")
            if uploaded_doc:
                fb.uploaded_document = uploaded_doc
                updates.append("uploaded_document")
            if updates:
                fb.submitted_at = timezone.now()
                updates.append("submitted_at")
                fb.save(update_fields=updates)

                if member:
                    member_updates = set()
                    if not member.feedback_on_actions_received:
                        member.feedback_on_actions_received = True
                        member_updates.add("feedback_on_actions_received")
                    today = timezone.localdate()
                    if member.feedback_on_action_list_received != today:
                        member.feedback_on_action_list_received = today
                        member_updates.add("feedback_on_action_list_received")
                    if member_updates:
                        member.save(update_fields=list(member_updates))

                details = []
                if uploaded_doc:
                    details.append(
                        f"Document uploaded: {fb.latest_document_label or uploaded_doc.name}"
                    )
                if content:
                    snippet = (content[:97] + "…") if len(content) > 100 else content
                    details.append(f"Comments provided: {snippet}")
                if details:
                    _log_project_change(
                        project,
                        request.user,
                        "Action list feedback submitted",
                        " | ".join(details),
                    )

            return render(
                request,
                "synopsis/action_list_feedback_thanks.html",
                {
                    "project": project,
                    "feedback": fb,
                    "deadline": deadline,
                },
            )
    else:
        form = ActionListFeedbackForm(initial={"content": fb.content})

    return render(
        request,
        "synopsis/action_list_feedback_form.html",
        {
            "project": project,
            "token": fb.token,
            "feedback": fb,
            "deadline": deadline,
            "action_list": action_list,
            "form": form,
        },
    )


@login_required
def action_list_delete_revision(request, project_id, revision_id):
    if request.method != "POST":
        return HttpResponseBadRequest("Invalid request method.")

    project = get_object_or_404(Project, pk=project_id)
    if not _user_can_edit_project(request.user, project):
        messages.error(
            request,
            "Only assigned authors or managers can delete action list revisions.",
        )
        return redirect("synopsis:action_list_detail", project_id=project.id)

    action_list = getattr(project, "action_list", None)
    if not action_list:
        messages.error(request, "No action list exists for this project.")
        return redirect("synopsis:action_list_detail", project_id=project.id)

    revision = get_object_or_404(
        ActionListRevision, pk=revision_id, action_list=action_list
    )

    was_current = action_list.current_revision_id == revision.id
    file_name = revision.file.name
    revision.delete()

    next_revision = (
        action_list.revisions.exclude(pk=revision_id)
        .order_by("-uploaded_at", "-id")
        .first()
    )

    if was_current:
        if next_revision:
            try:
                base_name, size_text = _apply_revision_to_action_list(
                    action_list, next_revision
                )
            except (FileNotFoundError, ValueError):
                action_list.current_revision = next_revision
                action_list.save(update_fields=["current_revision"])
                base_name = next_revision.original_name or os.path.basename(
                    next_revision.file.name
                )
                size_text = _format_file_size(next_revision.file_size)
        else:
            action_list.current_revision = None
            action_list.save(update_fields=["current_revision"])
            base_name = "none"
            size_text = "—"
    else:
        base_name = revision.original_name or os.path.basename(file_name)
        size_text = _format_file_size(revision.file_size)

    _log_project_change(
        project,
        request.user,
        "Action list revision deleted",
        f"Revision file: {file_name or 'unknown'}; Remaining current: {base_name} ({size_text})",
    )

    messages.success(request, "Action list revision deleted.")
    return redirect("synopsis:action_list_detail", project_id=project.id)


@login_required
def advisory_send_invite_member(request, project_id, member_id):
    project = get_object_or_404(Project, id=project_id)
    m = get_object_or_404(AdvisoryBoardMember, id=member_id, project=project)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")
    if not m.email:
        messages.error(request, "This member has no email.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    inv = AdvisoryBoardInvitation.objects.create(
        project=project,
        member=m,
        email=m.email,
        invited_by=request.user,
        due_date=m.response_date,
    )
    yes_url = request.build_absolute_uri(
        reverse("synopsis:advisory_invite_reply", args=[inv.token, "yes"])
    )
    no_url = request.build_absolute_uri(
        reverse("synopsis:advisory_invite_reply", args=[inv.token, "no"])
    )
    deadline_txt = m.response_date.strftime("%d %b %Y") if m.response_date else "—"

    subject = email_subject("invite", project, m.response_date)
    text = (
        f"Dear {m.first_name or 'colleague'},\n\n"
        f"You are invited to advise on '{project.title}'.\n"
        f"Please reply by: {deadline_txt}\n\n"
        f"Yes: {yes_url}\nNo:  {no_url}\n\n"
        f"Thank you."
    )
    html = (
        f"<p>Dear {m.first_name or 'colleague'},</p>"
        f"<p>You are invited to advise on '<strong>{project.title}</strong>'.</p>"
        f"<p><strong>Please reply by: {deadline_txt}</strong></p>"
        f"<p>"
        f"<a href='{yes_url}' style='padding:8px 12px;border:1px solid #0a0;text-decoration:none;'>Yes</a> "
        f"<a href='{no_url}' style='padding:8px 12px;border:1px solid #a00;text-decoration:none;margin-left:8px;'>No</a>"
        f"</p>"
    )

    msg = EmailMultiAlternatives(
        subject,
        text,
        to=[m.email],
        reply_to=reply_to_list(getattr(request.user, "email", None)),
    )
    msg.attach_alternative(html, "text/html")
    msg.send()

    m.invite_sent = True
    m.invite_sent_at = timezone.now()
    m.save(update_fields=["invite_sent", "invite_sent_at"])

    messages.success(request, f"Invitation sent to {m.email}.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)
