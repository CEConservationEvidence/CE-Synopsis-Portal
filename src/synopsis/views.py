import datetime as dt

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.core.mail import EmailMultiAlternatives, send_mail
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
    AdvisoryBulkInviteForm,
    ProtocolSendForm,
    ReminderScheduleForm,
    ProtocolReminderScheduleForm,
    ParticipationConfirmForm,
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
)
from .utils import ensure_global_groups, email_subject, reply_to_list


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


def _advisory_board_context(
    project,
    *,
    member_form=None,
    reminder_form=None,
    protocol_form=None,
):
    members = project.advisory_board_members.order_by("last_name", "first_name")
    accepted_members = members.filter(response="Y")
    declined_members = members.filter(response="N")
    pending_members = members.exclude(response__in=["Y", "N"])

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
        sent_protocol_at__isnull=False
    ).exclude(response="N")
    protocol_pending_dates = [
        d
        for d in protocol_members.filter(
            feedback_on_protocol_deadline__isnull=False
        )
        .order_by("feedback_on_protocol_deadline")
        .values_list("feedback_on_protocol_deadline", flat=True)
    ]
    if protocol_form is None:
        protocol_initial = {}
        if protocol_pending_dates:
            protocol_initial["deadline"] = protocol_pending_dates[0]
        protocol_form = ProtocolReminderScheduleForm(initial=protocol_initial)

    if member_form is None:
        member_form = AdvisoryBoardMemberForm()

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
    class Meta:
        model = Project
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
        }


@login_required
def project_create(request):
    if request.method == "POST":
        pform = ProjectCreateForm(request.POST)
        aform = AssignAuthorsForm(request.POST)
        fform = FunderForm(request.POST)
        if pform.is_valid() and aform.is_valid() and fform.is_valid():
            project = pform.save()

            _log_project_change(
                project, request.user, "Project created", f"Title: {project.title}"
            )

            # Assign authors via UserRole
            authors = aform.cleaned_data.get("authors") or []
            for user in authors:
                UserRole.objects.get_or_create(
                    user=user, project=project, role="author"
                )
            if authors:
                author_labels = ", ".join(
                    user.get_full_name() or user.username for user in authors
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
                    f"Funds allocated: {_format_value(funder.funds_allocated)}; "
                    f"Dates: {_format_value(funder.fund_start_date)} to {_format_value(funder.fund_end_date)}"
                )
                _log_project_change(project, request.user, "Added funder", details)

            messages.success(request, "Project created.")
            return redirect("synopsis:project_hub", project_id=project.id)
    else:
        pform = ProjectCreateForm()
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
            "phase_labels": phase_labels,
            "next_phase": next_phase,
            "next_phase_label": next_phase_label,
            "last_phase_event": last_event,
            "authors": list(project.author_users),
            "change_log_entries": change_log_entries,
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
                    f"Funds allocated: {_format_value(funder.funds_allocated)}; "
                    f"Dates: {_format_value(funder.fund_start_date)} to {_format_value(funder.fund_end_date)}"
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
                    updated.contact_first_name,
                    updated.contact_last_name,
                )
                updated.save()
                changes = []
                for field in (
                    "organisation",
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
        detail = f"Removed funder {Funder.build_display_name(funder.organisation, funder.contact_first_name, funder.contact_last_name)}"
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

    if request.method == "POST":
        title = project.title
        project.delete()
        messages.success(request, f"Project '{title}' deleted.")
        return redirect("synopsis:dashboard")

    return render(
        request,
        "synopsis/project_confirm_delete.html",
        {"project": project},
    )


@login_required
def protocol_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)

    if request.method == "POST":
        form = ProtocolUpdateForm(request.POST, request.FILES, instance=protocol)
        if form.is_valid():
            old_stage = protocol.stage if protocol else None
            old_file = (
                protocol.document.name if protocol and protocol.document else None
            )
            old_text = protocol.text_version if protocol else ""

            obj = form.save(commit=False)
            obj.project = project
            obj.save()
            form.save_m2m()

            new_file = obj.document.name if obj.document else None
            changes = []

            if protocol is None:
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

            new_text = obj.text_version or ""
            if old_text != new_text:
                changes.append(
                    f"Text updated (length {len(old_text)} → {len(new_text)} chars)"
                )

            if changes:
                _log_project_change(
                    project,
                    request.user,
                    "Protocol updated",
                    "; ".join(changes),
                )

            messages.success(request, "Protocol updated.")
            return redirect("synopsis:protocol_detail", project_id=project.id)
    else:
        form = ProtocolUpdateForm(instance=protocol)

    return render(
        request,
        "synopsis/protocol_detail.html",
        {"project": project, "protocol": protocol, "form": form},
    )


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
        protocol.save(update_fields=["document"])
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


@login_required
def manager_dashboard(request):
    if not request.user.is_staff:
        messages.error(request, "Manager access only.")
        return redirect("synopsis:dashboard")

    ensure_global_groups()
    users = User.objects.order_by("username")
    return render(request, "synopsis/manager_dashboard.html", {"users": users})


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

    messages.success(
        request,
        f"Scheduled reminders for {updated} member(s)."
    )
    return redirect("synopsis:advisory_board_list", project_id=project.id)


@login_required
def advisory_schedule_protocol_reminders(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    if request.method != "POST":
        return HttpResponseBadRequest("POST required")

    form = ProtocolReminderScheduleForm(request.POST)
    pending_members = project.advisory_board_members.filter(
        sent_protocol_at__isnull=False
    ).exclude(response="N")

    if not form.is_valid():
        context = _advisory_board_context(project, protocol_form=form)
        return render(request, "synopsis/advisory_board_list.html", context)

    deadline = form.cleaned_data["deadline"]
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
        updated += 1

    if updated:
        _log_project_change(
            project,
            request.user,
            "Scheduled protocol reminders",
            f"Protocol deadline {deadline} for {updated} member(s)",
        )

    messages.success(request, f"Protocol reminder scheduled for {updated} member(s).")
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
                member.participation_statement = "Confirmed participation via legacy link"
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

        if request.method == "POST":
            form = ParticipationConfirmForm(request.POST)
            if form.is_valid():
                statement = form.cleaned_data["statement"].strip()
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
                    {"member": member, "project": inv.project, "accepted": inv.accepted},
                )
        else:
            form = ParticipationConfirmForm()

        return render(
            request,
            "synopsis/advisory_participation_confirm.html",
            {
                "project": inv.project,
                "invitation": inv,
                "form": form,
                "member": member,
            },
        )

    if membe:
        updates = {"response", "response_date", "participation_confirmed", "participation_confirmed_at", "participation_statement"}
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
            f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y') if m.feedback_on_protocol_deadline else '—'}\n"
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
        AdvisoryBoardMember.objects.filter(project=project)
        .exclude(email__isnull=True)
        .exclude(email__exact="")
    )

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = email_subject("protocol_review", project)

    sent = 0
    for m in members:
        text = (
            f"Dear {m.first_name or 'colleague'},\n\n"
            f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
            f"Deadline for protocol feedback: "
            f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y') if m.feedback_on_protocol_deadline else '—'}\n"
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

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = email_subject("protocol_review", project)
    text = (
        f"Dear {m.first_name or 'colleague'},\n\n"
        f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
        f"Deadline for protocol feedback: "
        f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y') if m.feedback_on_protocol_deadline else '—'}\n"
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
                AdvisoryBoardMember.objects.filter(project=project)
                .exclude(email__isnull=True)
                .exclude(email__exact="")
            )
            content = form.cleaned_data["content"]
            message_body = form.cleaned_data.get("message") or ""
            sent = 0
            for m in members:
                fb = ProtocolFeedback.objects.create(
                    project=project, member=m, email=m.email
                )
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
    if request.method == "POST":
        form = ProtocolSendForm(request.POST)
        if form.is_valid():
            content = form.cleaned_data["content"]
            message_body = form.cleaned_data.get("message") or ""
            fb = ProtocolFeedback.objects.create(
                project=project, member=m, email=m.email
            )
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
    if request.method == "POST":
        content = (request.POST.get("content") or "").strip()
        if not content:
            messages.error(request, "Please enter your comments.")
        else:
            fb.content = content
            fb.submitted_at = timezone.now()
            fb.save(update_fields=["content", "submitted_at"])
            return render(
                request,
                "synopsis/protocol_feedback_thanks.html",
                {"project": fb.project},
            )
    return render(
        request,
        "synopsis/protocol_feedback_form.html",
        {"project": fb.project, "token": fb.token, "feedback": fb},
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
