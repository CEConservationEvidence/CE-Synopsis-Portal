import datetime as dt
import hashlib
import os
import uuid
from decimal import Decimal

import rispy

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.core.files.base import ContentFile
from django.core.mail import EmailMultiAlternatives, send_mail
from django.db import transaction
from django.db.models import Count
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django import forms
from django.views.decorators.csrf import csrf_exempt

from .forms import (
    ProtocolUpdateForm,
    CreateUserForm,
    AdvisoryBoardMemberForm,
    AdvisoryInviteForm,
    AssignAuthorsForm,
    FunderForm,
    ProjectDeleteForm,
    AdvisoryBulkInviteForm,
    ProtocolSendForm,
    ReminderScheduleForm,
    ProtocolReminderScheduleForm,
    ParticipationConfirmForm,
    ProtocolFeedbackForm,
    ProtocolFeedbackCloseForm,
    ReferenceBatchUploadForm,
    ReferenceScreeningForm,
)
from .models import (
    Project,
    Protocol,
    AdvisoryBoardMember,
    AdvisoryBoardInvitation,
    Funder,
    UserRole,
    ProjectPhaseEvent,
    ProjectChangeLog,
    ProtocolFeedback,
    ReferenceSourceBatch,
    Reference,
    ProtocolRevision,
)
from .utils import ensure_global_groups, email_subject, reply_to_list, reference_hash


def _user_is_manager(user) -> bool:
    if not getattr(user, "is_authenticated", False):
        return False
    if user.is_staff:
        return True
    return user.groups.filter(name="manager").exists()


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


def _advisory_board_context(
    project,
    *,
    member_form=None,
    reminder_form=None,
    protocol_form=None,
    feedback_close_form=None,
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

    protocol_obj = getattr(project, "protocol", None)
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
    }

    return {
        "project": project,
        "accepted_members": accepted_members,
        "declined_members": declined_members,
        "pending_members": pending_members,
        "member_sections": [
            ("Accepted members", accepted_members, "No accepted members yet."),
            ("Pending members", pending_members, "No pending members yet."),
            ("Declined members", declined_members, "No declined members yet."),
        ],
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
        pform.fields["start_date"].initial = today
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
                    author_labels = ", ".join(
                        _user_display(user) for user in authors
                    )
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
            hidden_project_form.fields["start_date"].initial = today

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
    can_manage = _user_is_manager(request.user)

    funders = list(project.funders.all())
    funders.sort(
        key=lambda f: (
            f.fund_start_date or dt.date.max,
            (f.organisation or f.contact_last_name or f.contact_first_name or "").lower(),
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
                    f"Title: {_format_value(funder.contact_title)}"
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
        {"project": project, "form": form, "next_url": next_url},
    )


@login_required
def protocol_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    can_manage = _user_is_manager(request.user)
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

    existing_file_name = (
        protocol.document.name if protocol and protocol.document else ""
    )
    has_existing_file = bool(existing_file_name or revision_entries)
    first_upload_pending = not has_existing_file
    final_stage_locked = bool(
        protocol and protocol.stage == "final" and has_existing_file
    )

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

# TODO: only a manager can delete protocols and other material - apply user permissions functionality here and elsewhere later.
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


@login_required
def manager_dashboard(request):
    if not request.user.is_staff:
        messages.error(request, "Manager access only.")
        return redirect("synopsis:dashboard")

    ensure_global_groups()
    users = User.objects.order_by("username")

    projects = (
        Project.objects.prefetch_related("userrole_set__user")
        .order_by("-created_at", "-id")
    )
    project_entries = []
    for project in projects:
        authors = [
            role.user
            for role in project.userrole_set.all()
            if role.role == "author"
        ]
        form = ProjectDeleteForm(
            project=project, auto_id=f"id_project_{project.id}_%s"
        )
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


@login_required
def advisory_board_list(request, project_id):
    project = get_object_or_404(Project, pk=project_id)

    if request.method == "POST" and request.POST.get("action") == "add_member":
        form = AdvisoryBoardMemberForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.project = project
            m.save()
            messages.success(request, "Advisory Board member added.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
        context = _advisory_board_context(project, member_form=form)
        return render(request, "synopsis/advisory_board_list.html", context)

    form = AdvisoryBoardMemberForm()
    context = _advisory_board_context(project, member_form=form)
    return render(request, "synopsis/advisory_board_list.html", context)


@login_required
def advisory_schedule_reminders(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = ReminderScheduleForm(request.POST)
    pending_members = project.advisory_board_members.filter(invite_sent=False)

    if not form.is_valid():
        context = _advisory_board_context(project, reminder_form=form)
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
        context = _advisory_board_context(project, protocol_form=form)
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

    messages.success(request, f"Protocol reminder scheduled for {updated} member(s). Reminder now set as required.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def reference_batch_list(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    batches = project.reference_batches.select_related("uploaded_by").order_by(
        "-created_at", "-id"
    )
    summary = {
        "total_references": project.references.count(),
        "pending": project.references.filter(screening_status="pending").count(),
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
        },
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
                try:
                    records = rispy.loads(raw_bytes.decode("utf-8", errors="ignore"))
                except Exception as exc:  # pragma: no cover - parser errors
                    form.add_error("ris_file", f"Could not parse RIS content ({exc}).")
                else:
                    if not records:
                        form.add_error(
                            "ris_file",
                            "No RIS records were detected. Please ensure the file uses RIS tags (e.g. 'TY  -', 'TI  -').",
                        )
                    else:
                        with transaction.atomic():
                            batch = ReferenceSourceBatch.objects.create(
                                project=project,
                                label=form.cleaned_data["label"],
                                source_type=form.cleaned_data["source_type"],
                                search_date=form.cleaned_data.get("search_date"),
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
                                    abstract=_extract_reference_field(
                                        record, "abstract"
                                    ),
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

    if member_id:
        member = get_object_or_404(AdvisoryBoardMember, pk=member_id, project=project)
        initial["email"] = member.email
        if member.response_date:
            initial["due_date"] = member.response_date

    if request.method == "POST":
        form = AdvisoryInviteForm(request.POST)
        if form.is_valid():
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

            include_protocol = form.cleaned_data.get("include_protocol")
            protocol_content = form.cleaned_data.get("protocol_content")
            proto = getattr(project, "protocol", None)
            if include_protocol and proto:
                if protocol_content == "file" and getattr(proto, "document", None):
                    proto_url = request.build_absolute_uri(proto.document.url)
                    text += f"\nProtocol: {proto_url}\n"
                    html += f"<p><strong>Protocol:</strong> <a href='{proto_url}'>View document</a></p>"
                elif protocol_content == "text" and (proto.text_version or "").strip():
                    html += "<hr>" + proto.text_version

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
                member.save(update_fields=["invite_sent", "invite_sent_at"])

            messages.success(request, f"Invitation sent to {email}.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = AdvisoryInviteForm(initial=initial)

    return render(
        request,
        "synopsis/advisory_invite_form.html",
        {"project": project, "form": form, "member": member},
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
        member.participation_statement = ""
        member.save(update_fields=list(updates))

    inv.accepted = False
    inv.responded_at = timezone.now()
    inv.save(update_fields=["accepted", "responded_at"])

    return render(
        request,
        "synopsis/invite_thanks.html",
        {"member": member, "project": inv.project, "accepted": inv.accepted},
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
    if request.method == "POST":
        form = AdvisoryBulkInviteForm(request.POST)
        if form.is_valid():
            members = (
                AdvisoryBoardMember.objects.filter(project=project)
                .exclude(email__isnull=True)
                .exclude(email__exact="")
            )
            include_protocol = form.cleaned_data.get("include_protocol")
            protocol_content = form.cleaned_data.get("protocol_content")
            message_body = form.cleaned_data.get("message") or ""
            sent = 0
            for m in members:
                inv = AdvisoryBoardInvitation.objects.create(
                    project=project,
                    member=m,
                    email=m.email,
                    invited_by=request.user,
                    due_date=form.cleaned_data.get("due_date") or m.response_date,
                )
                yes_url = request.build_absolute_uri(
                    reverse("synopsis:advisory_invite_reply", args=[inv.token, "yes"])
                )
                no_url = request.build_absolute_uri(
                    reverse("synopsis:advisory_invite_reply", args=[inv.token, "no"])
                )
                deadline_txt = (
                    (form.cleaned_data.get("due_date") or m.response_date).strftime(
                        "%d %b %Y"
                    )
                    if (form.cleaned_data.get("due_date") or m.response_date)
                    else "—"
                )

                subject = email_subject(
                    "invite",
                    project,
                    (form.cleaned_data.get("due_date") or m.response_date),
                )
                text = (
                    f"Dear {m.first_name or 'colleague'},\n\n"
                    f"You are invited to advise on '{project.title}'.\n"
                    f"Please reply by: {deadline_txt}\n\n"
                    f"Yes: {yes_url}\nNo:  {no_url}\n\n"
                    "After clicking Yes you'll be asked to confirm you can actively participate and provide valuable input.\n\n"
                    f"{message_body}\n"
                )
                html = (
                    f"<p>Dear {m.first_name or 'colleague'},</p>"
                    f"<p>You are invited to advise on '<strong>{project.title}</strong>'.</p>"
                    f"<p><strong>Please reply by: {deadline_txt}</strong></p>"
                    f"<p>"
                    f"<a href='{yes_url}' style='padding:8px 12px;border:1px solid #0a0;text-decoration:none;'>Yes</a> "
                    f"<a href='{no_url}' style='padding:8px 12px;border:1px solid #a00;text-decoration:none;margin-left:8px;'>No</a>"
                    f"</p>"
                    f"<p>{message_body}</p>"
                    "<p><em>After clicking Yes you'll confirm that you will actively participate and provide valuable input.</em></p>"
                )

                proto = getattr(project, "protocol", None)
                if include_protocol and proto:
                    if protocol_content == "file" and getattr(proto, "document", None):
                        proto_url = request.build_absolute_uri(proto.document.url)
                        text += f"\nProtocol: {proto_url}\n"
                        html += f"<p><strong>Protocol:</strong> <a href='{proto_url}'>View document</a></p>"
                    elif (
                        protocol_content == "text"
                        and (proto.text_version or "").strip()
                    ):
                        html += "<hr>" + proto.text_version

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

                m.invite_sent = True
                m.invite_sent_at = timezone.now()
                m.save(update_fields=["invite_sent", "invite_sent_at"])
                sent += 1

            messages.success(request, f"Sent {sent} invite(s).")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = AdvisoryBulkInviteForm()

    return render(
        request,
        "synopsis/advisory_invite_compose_all.html",
        {"project": project, "form": form},
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

    messages.success(request, f"Sent protocol to {m.email}.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_send_protocol_compose_all(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    proto = getattr(project, "protocol", None)
    if not proto:
        messages.error(request, "No protocol configured for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)
    if request.method == "POST":
        form = ProtocolSendForm(request.POST)
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
        form = ProtocolSendForm(initial={"content": "file"})
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
    if request.method == "POST":
        form = ProtocolSendForm(request.POST)
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
        form = ProtocolSendForm(initial={"content": "file"})
    return render(
        request,
        "synopsis/protocol_send_compose.html",
        {"project": project, "form": form, "scope": "member", "member": m},
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
        },
    )


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
