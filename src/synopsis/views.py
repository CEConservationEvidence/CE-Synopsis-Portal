from django.utils import timezone
from datetime import datetime
from django.conf import settings
from django.http import HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.models import User, Group
from django import forms
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt
from django.core.mail import EmailMultiAlternatives

from django.core.mail import send_mail
from .models import Project, Protocol, AdvisoryBoardMember, AdvisoryBoardInvitation
from .forms import (
    ProtocolUpdateForm,
    CreateUserForm,
    AdvisoryBoardMemberForm,
    AdvisoryInviteForm,
)
from .utils import ensure_global_groups


# -------- Dashboard & Project Hub (you already had these; keeping minimal) --------
@login_required
def dashboard(request):
    projects = Project.objects.order_by("-created_at")
    return render(request, "synopsis/dashboard.html", {"projects": projects})


class ProjectCreateForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["title", "status"]


@login_required
def project_create(request):
    if request.method == "POST":
        form = ProjectCreateForm(request.POST)
        if form.is_valid():
            project = form.save()
            messages.success(request, "Project created.")
            return redirect("synopsis:project_hub", project_id=project.id)
    else:
        form = ProjectCreateForm()
    return render(request, "synopsis/project_create.html", {"form": form})


@login_required
def project_hub(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    return render(
        request, "synopsis/project_hub.html", {"project": project, "protocol": protocol}
    )


@login_required
def protocol_detail(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    protocol = getattr(project, "protocol", None)
    if request.method == "POST":
        form = ProtocolUpdateForm(request.POST, request.FILES, instance=protocol)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.project = project
            obj.save()
            messages.success(request, "Protocol updated.")
            return redirect("synopsis:protocol_detail", project_id=project.id)
    else:
        form = ProtocolUpdateForm(instance=protocol)
    return render(
        request,
        "synopsis/protocol_detail.html",
        {"project": project, "protocol": protocol, "form": form},
    )


# -------------------------- Manager: users (global) -------------------------------
@login_required
def manager_dashboard(request):
    # Basic gate: show link only to staff; keep it simple
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
                # Put user in the selected global role group
                group = Group.objects.get(name=global_role)
                user.groups.add(group)

                if global_role == "manager":
                    user.is_staff = True  # minimal gate for manager dashboard
                    user.save(update_fields=["is_staff"])

                messages.success(request, f"User {email} created as {global_role}.")
                return redirect("synopsis:manager_dashboard")
    else:
        form = CreateUserForm()

    return render(request, "synopsis/user_create.html", {"form": form})


# --- NEW: Advisory Board list + add member ---
@login_required
def advisory_board_list(request, project_id):
    project = get_object_or_404(Project, pk=project_id)
    members = project.advisory_board_members.order_by("last_name", "first_name")

    # simple "add member" inline form on the page
    if request.method == "POST" and request.POST.get("action") == "add_member":
        form = AdvisoryBoardMemberForm(request.POST)
        if form.is_valid():
            m = form.save(commit=False)
            m.project = project
            m.save()
            messages.success(request, "Advisory Board member added.")
            return redirect("synopsis:advisory_board_list", project_id=project.id)
    else:
        form = AdvisoryBoardMemberForm()

    return render(
        request,
        "synopsis/advisory_board_list.html",
        {"project": project, "members": members, "form": form},
    )


# --- NEW: Create & send invite email (optionally prefilled from a member) ---
@login_required
def advisory_invite_create(request, project_id, member_id=None):
    project = get_object_or_404(Project, pk=project_id)
    initial = {}

    member = None
    if member_id:
        member = get_object_or_404(AdvisoryBoardMember, pk=member_id, project=project)
        initial["email"] = member.email

    if request.method == "POST":
        form = AdvisoryInviteForm(request.POST)
        if form.is_valid():
            email = form.cleaned_data["email"].strip()
            message_body = form.cleaned_data["message"] or ""
            inv = AdvisoryBoardInvitation.objects.create(
                project=project,
                email=email,
                invited_by=request.user,
            )
            accept_url = request.build_absolute_uri(
                reverse("synopsis:advisory_invite_accept", args=[str(inv.token)])
            )

            subject = f"[{project.title}] Advisory Board Invitation"
            body = (
                f"Hello,\n\n"
                f"You've been invited to join the advisory board for '{project.title}'.\n"
                f"Please accept here: {accept_url}\n\n"
                f"{message_body}\n\n"
                f"Thanks!"
            )

            send_mail(
                subject=subject,
                message=body,
                from_email=getattr(
                    settings, "DEFAULT_FROM_EMAIL", "no-reply@localhost"
                ),
                recipient_list=[email],
                fail_silently=False,
            )

            # mark member.invite_sent if we invited a known person
            if member:
                member.invite_sent = True
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


# --- NEW: Accept invite (public link from email) ---


@csrf_exempt  # keep friction low for demo; remove later if you like
def advisory_invite_accept(request, token):
    inv = get_object_or_404(AdvisoryBoardInvitation, token=token)
    if not inv.accepted:
        inv.accepted = True
        inv.responded_at = timezone.now()
        inv.save(update_fields=["accepted", "responded_at"])

        # ensure a member exists for this project/email
        member, created = AdvisoryBoardMember.objects.get_or_create(
            project=inv.project,
            email__iexact=inv.email,
            defaults={"first_name": "", "last_name": "", "organisation": ""},
        )
        # set response_date on the member (optional)
        if not member.response_date:
            member.response_date = timezone.now().date()
            member.response = "accepted"
            member.save(update_fields=["response_date", "response"])

    return render(
        request,
        "synopsis/advisory_invite_accept.html",
        {"project": inv.project, "invitation": inv},
    )


def advisory_invite_reply(request, token, choice):
    inv = get_object_or_404(AdvisoryBoardInvitation, token=token)
    m = inv.member

    choice = choice.lower()
    if choice not in ("yes", "no"):
        return HttpResponseBadRequest("Invalid choice")

    m.response = "Y" if choice == "yes" else "N"
    m.response_date = timezone.localdate()  # “Response date” = when they answered
    m.save(update_fields=["response", "response_date"])

    inv.accepted = choice == "yes"
    inv.responded_at = timezone.now()
    inv.save(update_fields=["accepted", "responded_at"])

    return render(
        request,
        "synopsis/invite_thanks.html",
        {"member": m, "project": inv.project, "accepted": inv.accepted},
    )


from django.core.mail import EmailMultiAlternatives
from django.urls import reverse
from django.contrib import messages
from django.shortcuts import redirect
from .models import Project, AdvisoryBoardMember, AdvisoryBoardInvitation


def send_advisory_invites(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    ids = request.POST.getlist("member_ids")  # checkbox list in the table
    members = AdvisoryBoardMember.objects.filter(project=project, id__in=ids)

    for m in members:
        inv = AdvisoryBoardInvitation.objects.create(
            project=project, member=m, email=m.email, invited_by=request.user
        )
        yes_url = request.build_absolute_uri(
            reverse("synopsis:advisory_invite_reply", args=[inv.token, "yes"])
        )
        no_url = request.build_absolute_uri(
            reverse("synopsis:advisory_invite_reply", args=[inv.token, "no"])
        )
        deadline_txt = m.response_date.strftime("%d %b %Y") if m.response_date else "—"

        subject = f"[{project.title}] Advisory Board Invitation"
        text = (
            f"Dear {m.first_name},\n\n"
            f"You are invited to advise on '{project.title}'.\n"
            f"Please reply by: {deadline_txt}\n\n"
            f"Yes: {yes_url}\n"
            f"No:  {no_url}\n\n"
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
        )

        msg = EmailMultiAlternatives(subject, text, to=[m.email])
        msg.attach_alternative(html, "text/html")
        msg.send()

        m.invite_sent = True
        m.invite_sent_at = timezone.now()
        m.save(update_fields=["invite_sent", "invite_sent_at"])

    messages.success(request, f"Sent {members.count()} invite(s).")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


def bulk_set_response_date(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    ids = request.POST.getlist("member_ids")
    date_str = request.POST.get("response_date")  # yyyy-mm-dd from a date input
    if not date_str:
        messages.error(request, "Please choose a date.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    d = datetime.strptime(date_str, "%Y-%m-%d").date()
    AdvisoryBoardMember.objects.filter(project=project, id__in=ids).update(
        response_date=d
    )
    messages.success(request, "Response date set.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)


def send_protocol(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not hasattr(project, "protocol"):
        messages.error(request, "No protocol uploaded for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    ids = request.POST.getlist("member_ids")
    members = AdvisoryBoardMember.objects.filter(project=project, id__in=ids)

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = f"[{project.title}] Protocol for review"
    for m in members:
        text = (
            f"Dear {m.first_name},\n\n"
            f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
            f"Deadline for protocol feedback: "
            f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y') if m.feedback_on_protocol_deadline else '—'}\n"
        )
        msg = EmailMultiAlternatives(subject, text, to=[m.email])
        msg.send()
        m.sent_protocol_at = timezone.now()
        m.save(update_fields=["sent_protocol_at"])

    messages.success(request, f"Sent protocol to {members.count()} member(s).")
    return redirect("synopsis:advisory_board_list", project_id=project.id)

@login_required
def advisory_send_protocol_bulk(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    if not hasattr(project, "protocol"):
        messages.error(request, "No protocol uploaded for this project.")
        return redirect("synopsis:advisory_board_list", project_id=project.id)

    # Send to all members that have an email
    members = (
        AdvisoryBoardMember.objects
        .filter(project=project)
        .exclude(email__isnull=True)
        .exclude(email__exact="")
    )

    proto_url = request.build_absolute_uri(project.protocol.document.url)
    subject = f"[{project.title}] Protocol for review"

    sent = 0
    for m in members:
        text = (
            f"Dear {m.first_name or 'colleague'},\n\n"
            f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
            f"Deadline for protocol feedback: "
            f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y') if m.feedback_on_protocol_deadline else '—'}\n"
        )
        msg = EmailMultiAlternatives(subject, text, to=[m.email])
        msg.send()
        m.sent_protocol_at = timezone.now()
        m.save(update_fields=["sent_protocol_at"])
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
    subject = f"[{project.title}] Protocol for review"
    text = (
        f"Dear {m.first_name or 'colleague'},\n\n"
        f"Please review the protocol for '{project.title}':\n{proto_url}\n\n"
        f"Deadline for protocol feedback: "
        f"{m.feedback_on_protocol_deadline.strftime('%d %b %Y') if m.feedback_on_protocol_deadline else '—'}\n"
    )
    msg = EmailMultiAlternatives(subject, text, to=[m.email])
    msg.send()

    m.sent_protocol_at = timezone.now()
    m.save(update_fields=["sent_protocol_at"])

    messages.success(request, f"Sent protocol to {m.email}.")
    return redirect("synopsis:advisory_board_list", project_id=project.id)