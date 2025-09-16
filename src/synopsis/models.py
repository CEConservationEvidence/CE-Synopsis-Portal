from django.utils import timezone
from django.db import models
from django.contrib.auth.models import User
import uuid

"""
TODO: Modularise models into synopsis/models/* (project.py, funding.py, protocol.py, etc.)
      once the schema stabilises. Everything is in one file for develpment but this should be made modular for other living evidence teams to easily adapt to their workflows.
TODO: Add permissions to models to restrict access based on user roles.
TODO: Add signals to notify users of changes in project status or roles.
TODO: Add versioning to protocol model to track changes over time. Furthermore, this should be extended to other models like the draft final synopsis document, summaries, actions, etc.
TODO: Add audit trails to track changes made to critical fields in models (define the data model for this).
TODO: Add comments to models where necessary to explain their purpose and usage (for other teams adapting this).
"""


class Project(models.Model):
    """A singular 'project' class (reusable by other living evidence teams hence the term is open here)."""

    title = models.CharField(max_length=255)
    status = models.CharField(
        max_length=50,
        choices=[
            ("planning", "Planning"),
            ("active", "Active"),
            ("completed", "Completed"),
            ("archived", "Archived"),
        ],
        default="planning",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.title

    PHASE_CHOICES = [
        ("draft_protocol", "Draft protocol"),
        ("invite_advisory_board", "Invite advisory board"),
        ("references_screening", "References screening"),
        ("summary_writing", "Summary writing"),
        ("draft_chapters", "Draft chapters"),
        ("draft_synopsis", "Draft synopsis"),
        ("final_review", "Final review"),
        ("publication", "Publication"),
    ]

    phase_manual = models.CharField(
        max_length=50, choices=PHASE_CHOICES, null=True, blank=True
    )
    phase_manual_updated = models.DateTimeField(null=True, blank=True)

    def compute_phase(self):
        """Infer a best-effort phase from related activity.
        This does not persist; it is derived for UI.
        """

        proto = getattr(self, "protocol", None)
        if not proto or not getattr(proto, "document", None):
            return "draft_protocol"

        has_invites = AdvisoryBoardInvitation.objects.filter(project=self).exists()
        has_member_invites = AdvisoryBoardMember.objects.filter(
            project=self, invite_sent=True
        ).exists()
        if not (has_invites or has_member_invites):
            return "invite_advisory_board"

        any_accept = (
            AdvisoryBoardInvitation.objects.filter(project=self, accepted=True).exists()
            or AdvisoryBoardMember.objects.filter(
                project=self, response__in=["Y", "accepted"]
            ).exists()
        )
        if any_accept:
            if (
                AdvisoryBoardMember.objects.filter(
                    project=self,
                    feedback_on_actions_received=True,
                ).exists()
                or AdvisoryBoardMember.objects.filter(
                    project=self, feedback_on_list=True
                ).exists()
            ):
                return "summary_writing"

            if (
                AdvisoryBoardMember.objects.filter(
                    project=self,
                    added_to_protocol_doc=True,
                ).exists()
                or AdvisoryBoardMember.objects.filter(
                    project=self, feedback_on_protocol_received__isnull=False
                ).exists()
            ):
                return "draft_chapters"

            if AdvisoryBoardMember.objects.filter(
                project=self, feedback_on_guidance=True
            ).exists():
                return "draft_synopsis"

            return "references_screening"
        return "invite_advisory_board"

    def _phase_order(self):
        return [p for p, _ in self.PHASE_CHOICES]

    def _phase_index(self, key):
        try:
            return self._phase_order().index(key)
        except ValueError:
            return 0

    @property
    def phase(self):
        auto = self.compute_phase()
        manual = self.phase_manual or auto
        return manual if self._phase_index(manual) >= self._phase_index(auto) else auto

    def get_phase_display(self):
        mapping = dict(self.PHASE_CHOICES)
        return mapping.get(self.phase, self.phase)

    @property
    def author_users(self):
        """Return the users assigned as authors for this project."""
        return User.objects.filter(
            userrole__project=self, userrole__role="author"
        ).order_by("username")


class ProjectPhaseEvent(models.Model):
    """Audit trail for phase confirmations."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="phase_events"
    )
    phase = models.CharField(max_length=50, choices=Project.PHASE_CHOICES)
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    confirmed_at = models.DateTimeField(default=timezone.now, editable=False)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-confirmed_at", "-id"]

    def __str__(self):
        return (
            f"{self.project.title}: {self.phase} @ {self.confirmed_at:%Y-%m-%d %H:%M}"
        )


class ProjectChangeLog(models.Model):
    """Records manual changes to a project's metadata (authors, funders, etc.)."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="change_log"
    )
    changed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=100)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        who = self.changed_by or "system"
        return f"{self.project.title}: {self.action} ({who})"


class VocabularyTerm(models.Model):
    """
    Table for all controlled lists; type distinguishes the list.
    This model is specifically for CE but can be adapted by other teams or dropped entirely.
    """

    TYPE_CHOICES = [
        ("action", "Action / Intervention"),
        ("threat", "Threat"),
        ("taxon", "Taxon"),
        ("species", "Species"),
        ("habitat", "Habitat"),
        ("location", "Location"),
        ("design", "Research design"),
        ("keyword", "Keyword"),
    ]
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    label = models.CharField(max_length=255)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        indexes = [models.Index(fields=["type", "label"])]

    def __str__(self):
        return f"{self.get_type_display()}: {self.label}"


class UserRole(models.Model):
    ROLE_CHOICES = [
        ("manager", "Manager"),
        ("author", "Author"),
        ("advisory_board", "Advisory Board Member"),
        (
            "external_collaborator",
            "External Collaborator",
        ),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    project = models.ForeignKey(Project, on_delete=models.CASCADE)
    role = models.CharField(max_length=30, choices=ROLE_CHOICES)

    class Meta:
        unique_together = ("user", "project", "role")

    def __str__(self):
        return (
            f"{self.user.username} as {self.get_role_display()} in {self.project.title}"
        )


class Funder(models.Model):
    """A funder(s) for a project. It captures basic information about funders, related to a Project."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="funders"
    )
    name = models.CharField(max_length=255)
    contact_first_name = models.CharField(max_length=100, blank=True)
    contact_last_name = models.CharField(max_length=100, blank=True)
    organisation = models.CharField(max_length=255, blank=True)
    funds_allocated = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    fund_start_date = models.DateField(null=True, blank=True)
    fund_end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        label = self.organisation or self.name
        return f"{label} ({self.project.title})"

    @staticmethod
    def build_display_name(
        organisation: str | None, first: str | None, last: str | None
    ) -> str:
        organisation = (organisation or "").strip()
        first = (first or "").strip()
        last = (last or "").strip()
        if organisation:
            return organisation
        names = [part for part in [first, last] if part]
        if names:
            return " ".join(names)
        return "(Funder)"


class Protocol(models.Model):
    """The protocol document for a project, drafted by an author and finalized by manager."""

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="protocol"
    )
    document = models.FileField(upload_to="protocols/")
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    text_version = models.TextField(blank=True)
    STAGE_CHOICES = [("draft", "Draft"), ("final", "Final")]
    stage = models.CharField(max_length=20, choices=STAGE_CHOICES, default="draft")

    def __str__(self):
        return f"Protocol for {self.project.title}"


class AdvisoryBoardMember(models.Model):
    """An advisory board member for a project, where there can be multiple members per project.
    Note that this datamodel is speficific to CE and may need to be dropped by other teams.
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="advisory_board_members"
    )

    # Basic information on the member
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    organisation = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    location = models.CharField(max_length=100, blank=True)
    continent = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    # Invitation & communication tracking
    invite_sent = models.BooleanField(default=False)
    invite_sent_at = models.DateTimeField(null=True, blank=True)
    response_date = models.DateField(null=True, blank=True)
    response = models.CharField(
        max_length=100, blank=True
    )  # e.g. "accepted", "declined", etc.
    feedback_on_list = models.BooleanField(default=False)
    feedback_on_actions_received = models.BooleanField(default=False)
    wm_replied = models.BooleanField(default=False)  # TODO: What is wm? Clarify.
    feedback_added_to_action_list = models.BooleanField(default=False)
    reminder_sent = models.BooleanField(default=False)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    # Protocol interaction
    sent_protocol_at = models.DateTimeField(null=True, blank=True)
    protocol_reminder_sent = models.BooleanField(default=False)
    protocol_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    feedback_on_protocol_deadline = models.DateField(null=True, blank=True)
    feedback_on_protocol_received = models.DateField(null=True, blank=True)
    added_to_protocol_doc = models.BooleanField(default=False)
    feedback_on_guidance = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.first_name} {self.last_name or ''} ({self.email})"


class AdvisoryBoardInvitation(models.Model):
    """Simply tracks invitations sent to advisory board members for a project."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="invitations"
    )
    member = models.ForeignKey(
        "AdvisoryBoardMember",
        on_delete=models.CASCADE,
        related_name="invitations",
        null=True,
        blank=True,
    )
    email = models.EmailField()
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    accepted = models.BooleanField(null=True, blank=True)  # None until answered
    responded_at = models.DateTimeField(null=True, blank=True)

    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"Invite to {self.email} for {self.project.title}"


class ProtocolFeedback(models.Model):
    """Feedback submitted by advisory members (or invitees) on a project's protocol."""

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="protocol_feedback"
    )
    member = models.ForeignKey(
        "AdvisoryBoardMember",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="protocol_feedback",
    )
    invitation = models.ForeignKey(
        AdvisoryBoardInvitation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="protocol_feedback",
    )
    email = models.EmailField(blank=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    content = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["-submitted_at", "-created_at"]

    def __str__(self):
        who = self.member or self.email or "anonymous"
        return f"Feedback for {self.project.title} by {who}"
