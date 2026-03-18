import datetime as dt
import uuid

from django.contrib.auth.models import User
from django.contrib.postgres.fields import ArrayField
from django.core.validators import FileExtensionValidator
from django.db import models
from django.utils import timezone

"""
TODO: #16 Cleanup models.py by modularising models into separate files for organization and maintainability. Also add docstring comments (AI generated but reviewed) to explain purpose and usage.
TODO: #59 Modularise models into synopsis/models/* (project.py, funding.py, protocol.py, etc.)
      once the schema stabilises. Everything is in one file for development but this should be made modular for other living evidence teams to easily adapt to their workflows.
TODO: #60 Add permissions to restrict access based on user roles.
TODO: #61 Add signals to notify users of changes in project status or roles.
TODO: #62 Add versioning to protocol model to track changes over time. Furthermore, this should be extended to other models like the draft final synopsis document, summaries, actions, etc.
TODO: #63 Add audit trails to track changes made to critical fields in models (define the data model for this).
TODO: #64 Add comments to models where necessary to explain their purpose and usage (for other teams adapting this).
"""


class Project(models.Model):
    """A singular 'project' class (reusable by other living evidence teams hence the term is open here)."""

    title = models.CharField(max_length=255)
    start_date = models.DateField(null=True, blank=True)
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
    contact_title = models.CharField(max_length=50, blank=True)
    contact_first_name = models.CharField(max_length=100, blank=True)
    contact_last_name = models.CharField(max_length=100, blank=True)
    organisation = models.CharField(max_length=255, blank=True)
    organisation_details = models.TextField(blank=True)
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
        organisation: str | None,
        title: str | None,
        first: str | None,
        last: str | None,
    ) -> str:
        organisation = (organisation or "").strip()
        title = (title or "").strip()
        first = (first or "").strip()
        last = (last or "").strip()
        if organisation:
            return organisation
        names = [part for part in [title, first, last] if part]
        if names:
            return " ".join(names)
        return "(Funder)"

    def primary_contact(self):
        cached = getattr(self, "_prefetched_objects_cache", {}).get("contacts")
        if cached is not None:
            primary = next((contact for contact in cached if contact.is_primary), None)
            return primary or (cached[0] if cached else None)
        return (
            self.contacts.filter(is_primary=True).order_by("-id").first()
            or self.contacts.order_by("id").first()
        )

    def update_cached_contact_fields(self, *, save: bool = True):
        primary = self.primary_contact()
        self.contact_title = primary.title if primary else ""
        self.contact_first_name = primary.first_name if primary else ""
        self.contact_last_name = primary.last_name if primary else ""
        self.name = self.build_display_name(
            self.organisation,
            self.contact_title,
            self.contact_first_name,
            self.contact_last_name,
        )
        if save:
            self.save(
                update_fields=[
                    "name",
                    "contact_title",
                    "contact_first_name",
                    "contact_last_name",
                ]
            )

    def contact_display_name(self) -> str:
        primary = self.primary_contact()
        if primary:
            return primary.display_name()
        return self.organisation or "(Funder)"


class FunderContact(models.Model):
    funder = models.ForeignKey(
        Funder, on_delete=models.CASCADE, related_name="contacts"
    )
    title = models.CharField(max_length=50, blank=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ["-is_primary", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["funder"],
                condition=models.Q(is_primary=True),
                name="unique_primary_contact_per_funder",
            )
        ]

    def display_name(self) -> str:
        parts = [self.title, self.first_name, self.last_name]
        cleaned = [p.strip() for p in parts if p and p.strip()]
        return " ".join(cleaned) if cleaned else self.email or "—"

    def __str__(self):
        return self.display_name()


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
    feedback_closed_at = models.DateTimeField(null=True, blank=True)
    feedback_closure_message = models.TextField(blank=True)
    current_revision = models.ForeignKey(
        "ProtocolRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for",
    )

    def __str__(self):
        return f"Protocol for {self.project.title}"

    def latest_revision(self):
        if self.current_revision:
            return self.current_revision
        return self.revisions.order_by("-uploaded_at", "-id").first()


def protocol_revision_upload_path(instance, filename):
    return (
        f"protocol_revisions/{instance.protocol.project_id}/{uuid.uuid4()}_{filename}"
    )


class ProtocolRevision(models.Model):
    protocol = models.ForeignKey(
        Protocol, on_delete=models.CASCADE, related_name="revisions"
    )
    file = models.FileField(upload_to=protocol_revision_upload_path)
    stage = models.CharField(max_length=20, choices=Protocol.STAGE_CHOICES)
    change_reason = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="protocol_revisions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    original_name = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(default=0)
    version_label = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"Revision for {self.protocol.project.title} ({self.uploaded_at:%Y-%m-%d %H:%M})"


def action_list_upload_path(instance, filename):
    return f"action_lists/{instance.project_id}/{uuid.uuid4()}_{filename}"


def action_list_revision_upload_path(instance, filename):
    return f"action_list_revisions/{instance.action_list.project_id}/{uuid.uuid4()}_{filename}"


class ActionList(models.Model):
    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="action_list"
    )
    document = models.FileField(upload_to=action_list_upload_path)
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    text_version = models.TextField(blank=True)
    stage = models.CharField(
        max_length=20, choices=Protocol.STAGE_CHOICES, default="draft"
    )
    feedback_closed_at = models.DateTimeField(null=True, blank=True)
    feedback_closure_message = models.TextField(blank=True)
    current_revision = models.ForeignKey(
        "ActionListRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="current_for",
    )

    class Meta:
        verbose_name = "Action list"
        verbose_name_plural = "Action lists"

    def __str__(self):
        return f"Action list for {self.project.title}"

    def latest_revision(self):
        if self.current_revision:
            return self.current_revision
        return self.revisions.order_by("-uploaded_at", "-id").first()


class ActionListRevision(models.Model):
    action_list = models.ForeignKey(
        ActionList, on_delete=models.CASCADE, related_name="revisions"
    )
    file = models.FileField(upload_to=action_list_revision_upload_path)
    stage = models.CharField(max_length=20, choices=Protocol.STAGE_CHOICES)
    change_reason = models.TextField(blank=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_list_revisions",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    original_name = models.CharField(max_length=255, blank=True)
    file_size = models.BigIntegerField(default=0)
    version_label = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]

    def __str__(self):
        return f"Action list revision for {self.action_list.project.title} ({self.uploaded_at:%Y-%m-%d %H:%M})"


class CollaborativeSession(models.Model):
    DOCUMENT_PROTOCOL = "protocol"
    DOCUMENT_ACTION_LIST = "action_list"
    DOCUMENT_CHOICES = [
        (DOCUMENT_PROTOCOL, "Protocol"),
        (DOCUMENT_ACTION_LIST, "Action list"),
    ]

    DEFAULT_DURATION = dt.timedelta(hours=4)

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="collaborative_sessions",
    )
    document_type = models.CharField(max_length=20, choices=DOCUMENT_CHOICES)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    started_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collaborative_sessions_started",
    )
    started_at = models.DateTimeField(default=timezone.now, editable=False)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collaborative_sessions_ended",
    )
    end_reason = models.CharField(max_length=255, blank=True)
    change_summary = models.TextField(blank=True)
    last_callback_payload = models.JSONField(blank=True, null=True)
    last_participant_name = models.CharField(max_length=255, blank=True)
    initial_protocol_revision = models.ForeignKey(
        "ProtocolRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collaborative_sessions_started_protocol",
    )
    initial_action_list_revision = models.ForeignKey(
        "ActionListRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collaborative_sessions_started_action_list",
    )
    result_protocol_revision = models.ForeignKey(
        "ProtocolRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collaborative_sessions_completed_protocol",
    )
    result_action_list_revision = models.ForeignKey(
        "ActionListRevision",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="collaborative_sessions_completed_action_list",
    )
    invitations = models.ManyToManyField(
        "AdvisoryBoardInvitation",
        blank=True,
        related_name="collaborative_sessions",
    )

    class Meta:
        ordering = ["-started_at", "-id"]

    def __str__(self):
        label = dict(self.DOCUMENT_CHOICES).get(self.document_type, self.document_type)
        started = timezone.localtime(self.started_at).strftime("%Y-%m-%d %H:%M")
        return f"{label} session for {self.project.title} @ {started}"

    def has_expired(self, *, at_time=None, duration=None) -> bool:
        if not self.is_active:
            return False
        reference = self.last_activity_at or self.started_at
        limit = reference + (duration or self.DEFAULT_DURATION)
        return limit < (at_time or timezone.now())

    def mark_inactive(self, *, ended_by=None, reason="", when=None, extra_updates=None):
        if not self.is_active:
            return
        self.is_active = False
        self.ended_at = when or timezone.now()
        update_fields = ["is_active", "ended_at"]
        if ended_by is not None:
            self.ended_by = ended_by
            update_fields.append("ended_by")
        if reason:
            self.end_reason = reason
            update_fields.append("end_reason")
        if extra_updates:
            update_fields.extend(extra_updates)
        self.save(update_fields=sorted(set(update_fields)))

    def record_callback(self, payload: dict | None, *, when=None):
        self.last_activity_at = when or timezone.now()
        self.last_callback_payload = payload or {}
        self.save(update_fields=["last_activity_at", "last_callback_payload"])


# TODO: Refactor AdvisoryBoardMember columns for clarity and normalization:
#   - Consider renaming 'title', 'first_name', 'middle_name', 'last_name' for consistency with other models.
#   - Review if 'middle_name' is necessary or can be merged with 'first_name'.
#   - Evaluate if contact fields (email, phone) should be normalized into a separate ContactInfo model.
#   - Check for redundant or unused fields (e.g., 'feedback_on_actions_received', 'feedback_on_list', etc.).
#   - Document the purpose of each field and remove any that are not used in workflows.
#   - Ensure field naming is clear for teams adapting this model.
class AdvisoryBoardMember(models.Model):
    """An advisory board member for a project, where there can be multiple members per project.
    Note that this datamodel is speficific to CE and may need to be dropped by other teams.
    """

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="advisory_board_members"
    )

    # Basic information on the member
    title = models.CharField(max_length=20, blank=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    organisation = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    country = models.CharField(max_length=100, blank=True)
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
    wm_replied = models.BooleanField(default=False)
    feedback_added_to_action_list = models.BooleanField(default=False)
    reminder_sent = models.BooleanField(default=False)
    reminder_sent_at = models.DateTimeField(null=True, blank=True)

    # Action list interaction
    sent_action_list_at = models.DateTimeField(null=True, blank=True)
    action_list_reminder_sent = models.BooleanField(default=False)
    action_list_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    feedback_on_action_list_deadline = models.DateTimeField(null=True, blank=True)
    feedback_on_action_list_received = models.DateField(null=True, blank=True)
    added_to_action_list_doc = models.BooleanField(default=False)

    # Protocol interaction
    sent_protocol_at = models.DateTimeField(null=True, blank=True)
    protocol_reminder_sent = models.BooleanField(default=False)
    protocol_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    feedback_on_protocol_deadline = models.DateTimeField(null=True, blank=True)
    feedback_on_protocol_received = models.DateField(null=True, blank=True)
    added_to_protocol_doc = models.BooleanField(default=False)
    feedback_on_guidance = models.BooleanField(default=False)

    # Synopsis interaction
    sent_synopsis_at = models.DateTimeField(null=True, blank=True)
    synopsis_reminder_sent = models.BooleanField(default=False)
    synopsis_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    feedback_on_synopsis_deadline = models.DateTimeField(null=True, blank=True)
    feedback_on_synopsis_received = models.DateField(null=True, blank=True)
    added_to_synopsis_doc = models.BooleanField(default=False)

    # Participation confirmation
    participation_confirmed = models.BooleanField(default=False)
    participation_confirmed_at = models.DateTimeField(null=True, blank=True)
    participation_statement = models.TextField(blank=True)

    def __str__(self):
        parts = [self.title, self.first_name, self.last_name or ""]
        name = " ".join(part for part in parts if part).strip()
        return f"{name} ({self.email})"

    @property
    def latest_protocol_feedback(self):
        return self.protocol_feedback.order_by("-submitted_at", "-created_at").first()

    @property
    def latest_action_list_feedback(self):
        return self.action_list_feedback.order_by(
            "-submitted_at", "-created_at"
        ).first()


class AdvisoryBoardCustomField(models.Model):
    TYPE_TEXT = "text"
    TYPE_INTEGER = "integer"
    TYPE_BOOLEAN = "boolean"
    TYPE_DATE = "date"
    DATA_TYPE_CHOICES = [
        (TYPE_TEXT, "Text"),
        (TYPE_INTEGER, "Integer"),
        (TYPE_BOOLEAN, "Yes / No"),
        (TYPE_DATE, "Date"),
    ]

    SECTION_ACCEPTED = "accepted"
    SECTION_PENDING = "pending"
    SECTION_DECLINED = "declined"
    SECTION_CHOICES = [
        (SECTION_ACCEPTED, "Accepted"),
        (SECTION_PENDING, "Pending"),
        (SECTION_DECLINED, "Declined"),
    ]
    DISPLAY_GROUP_PERSONAL = "personal"
    DISPLAY_GROUP_INVITATION = "invitation"
    DISPLAY_GROUP_ACTION = "action"
    DISPLAY_GROUP_PROTOCOL = "protocol"
    DISPLAY_GROUP_SYNOPSIS = "synopsis"
    DISPLAY_GROUP_CUSTOM = "custom"
    DISPLAY_GROUP_CHOICES = [
        (DISPLAY_GROUP_PERSONAL, "Personal details"),
        (DISPLAY_GROUP_INVITATION, "Invitation"),
        (DISPLAY_GROUP_ACTION, "Action list"),
        (DISPLAY_GROUP_PROTOCOL, "Protocol"),
        (DISPLAY_GROUP_SYNOPSIS, "Synopsis"),
        (DISPLAY_GROUP_CUSTOM, "Custom section"),
    ]
    DISPLAY_GROUP_ORDER = [
        DISPLAY_GROUP_PERSONAL,
        DISPLAY_GROUP_INVITATION,
        DISPLAY_GROUP_ACTION,
        DISPLAY_GROUP_PROTOCOL,
        DISPLAY_GROUP_SYNOPSIS,
        DISPLAY_GROUP_CUSTOM,
    ]

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="advisory_custom_fields",
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, blank=True)
    data_type = models.CharField(
        max_length=20, choices=DATA_TYPE_CHOICES, default=TYPE_TEXT
    )
    sections = ArrayField(
        models.CharField(max_length=20, choices=SECTION_CHOICES),
        blank=True,
        default=list,
        help_text="Leave blank to display in every section.",
    )
    description = models.CharField(max_length=255, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    display_group = models.CharField(
        max_length=20,
        choices=DISPLAY_GROUP_CHOICES,
        default=DISPLAY_GROUP_CUSTOM,
        help_text="Choose where this column should appear in the advisory board table.",
    )
    is_required = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["display_order", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["project", "slug"], name="unique_custom_field_slug"
            )
        ]

    def __str__(self):
        return f"{self.name} ({self.project.title})"

    def applies_to(self, status: str) -> bool:
        if not self.sections:
            return True
        return status in self.sections

    def section_labels(self) -> list[str]:
        if not self.sections:
            return [label for _, label in self.SECTION_CHOICES]
        lookup = dict(self.SECTION_CHOICES)
        return [lookup.get(code, code.title()) for code in self.sections]

    @classmethod
    def group_fields_by_display(cls, fields: list["AdvisoryBoardCustomField"]):
        grouped: dict[str, list["AdvisoryBoardCustomField"]] = {
            key: [] for key in cls.DISPLAY_GROUP_ORDER
        }
        for field in fields:
            group = getattr(field, "display_group", None) or cls.DISPLAY_GROUP_CUSTOM
            grouped.setdefault(group, []).append(field)
        return grouped

    def clean_value(self, value):
        if value in (None, ""):
            return None
        if self.data_type == self.TYPE_TEXT:
            return str(value)
        if self.data_type == self.TYPE_INTEGER:
            return str(int(value))
        if self.data_type == self.TYPE_BOOLEAN:
            if isinstance(value, bool):
                return "true" if value else "false"
            value_str = str(value).strip().lower()
            if value_str in {"true", "1", "yes", "on"}:
                return "true"
            if value_str in {"false", "0", "no", "off"}:
                return "false"
            raise ValueError("Unrecognised boolean value")
        if self.data_type == self.TYPE_DATE:
            if isinstance(value, dt.date):
                return value.isoformat()
            return dt.date.fromisoformat(str(value)).isoformat()
        return str(value)

    def parse_value(self, value):
        if value in (None, ""):
            return None
        if self.data_type == self.TYPE_TEXT:
            return value
        if self.data_type == self.TYPE_INTEGER:
            return int(value)
        if self.data_type == self.TYPE_BOOLEAN:
            return str(value).lower() == "true"
        if self.data_type == self.TYPE_DATE:
            return dt.date.fromisoformat(str(value))
        return value

    def format_value(self, value):
        typed = self.parse_value(value)
        if typed is None:
            return ""
        if isinstance(typed, bool):
            return "Yes" if typed else "No"
        if isinstance(typed, dt.date):
            return typed.strftime("%Y-%m-%d")
        return str(typed)

    def get_value_for_member(self, member):
        try:
            stored = self.values.get(member=member)
        except AdvisoryBoardCustomFieldValue.DoesNotExist:
            return None
        return stored.value

    def set_value_for_member(self, member, value, *, changed_by=None):
        cleaned = self.clean_value(value) if value not in (None, "") else None
        current_value = self.get_value_for_member(member)
        current_normalized = current_value or ""
        new_normalized = cleaned or ""
        if current_normalized == new_normalized:
            return

        AdvisoryBoardCustomFieldValueHistory.objects.create(
            field=self,
            member=member,
            value=new_normalized,
            is_cleared=cleaned in (None, ""),
            changed_by=changed_by if isinstance(changed_by, User) else None,
        )

        if cleaned in (None, ""):
            AdvisoryBoardCustomFieldValue.objects.filter(
                field=self, member=member
            ).delete()
            return

        AdvisoryBoardCustomFieldValue.objects.update_or_create(
            field=self,
            member=member,
            defaults={"value": cleaned},
        )

    def save(self, *args, **kwargs):
        from django.utils.text import slugify

        if not self.slug:
            base_slug = slugify(self.name) or "field"
            slug = base_slug
            index = 1
            while (
                AdvisoryBoardCustomField.objects.filter(project=self.project, slug=slug)
                .exclude(pk=self.pk)
                .exists()
            ):
                index += 1
                slug = f"{base_slug}-{index}"
            self.slug = slug
        if self.display_order == 0:
            max_order = (
                AdvisoryBoardCustomField.objects.filter(project=self.project)
                .exclude(pk=self.pk)
                .aggregate(models.Max("display_order"))
                .get("display_order__max")
                or 0
            )
            self.display_order = max_order + 1
        super().save(*args, **kwargs)


class AdvisoryBoardCustomFieldValue(models.Model):
    field = models.ForeignKey(
        AdvisoryBoardCustomField,
        on_delete=models.CASCADE,
        related_name="values",
    )
    member = models.ForeignKey(
        AdvisoryBoardMember,
        on_delete=models.CASCADE,
        related_name="custom_values",
    )
    value = models.TextField(blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("field", "member")

    def __str__(self):
        return f"{self.field.name} for {self.member}"


class AdvisoryBoardCustomFieldValueHistory(models.Model):
    field = models.ForeignKey(
        AdvisoryBoardCustomField,
        on_delete=models.CASCADE,
        related_name="value_history",
    )
    member = models.ForeignKey(
        AdvisoryBoardMember,
        on_delete=models.CASCADE,
        related_name="custom_value_history",
    )
    value = models.TextField(blank=True)
    is_cleared = models.BooleanField(default=False)
    changed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="custom_field_value_history",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        action = "cleared" if self.is_cleared else "set"
        return f"{self.field.name} {action} for {self.member} @ {self.created_at:%Y-%m-%d %H:%M}"


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
    accepted = models.BooleanField(
        null=True, blank=True
    )  # None until answered but fallback to what?
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
    uploaded_document = models.FileField(
        upload_to="protocol_feedback_uploads/",
        null=True,
        blank=True,
    )
    protocol_document_name = models.CharField(max_length=255, blank=True)
    protocol_document_last_updated = models.DateTimeField(null=True, blank=True)
    protocol_stage_snapshot = models.CharField(max_length=20, blank=True)
    feedback_deadline_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-created_at"]

    def __str__(self):
        who = self.member or self.email or "anonymous"
        return f"Feedback for {self.project.title} by {who}"

    def latest_document_label(self) -> str:
        if self.uploaded_document:
            return self.uploaded_document.name.rsplit("/", 1)[-1]
        return ""

    def snapshot_deadline(self):
        return self.feedback_deadline_at


class ActionListFeedback(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="action_list_feedback"
    )
    action_list = models.ForeignKey(
        ActionList, on_delete=models.SET_NULL, null=True, blank=True
    )
    member = models.ForeignKey(
        "AdvisoryBoardMember",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_list_feedback",
    )
    invitation = models.ForeignKey(
        AdvisoryBoardInvitation,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="action_list_feedback",
    )
    email = models.EmailField(blank=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    content = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    uploaded_document = models.FileField(
        upload_to="action_list_feedback_uploads/",
        null=True,
        blank=True,
    )
    action_list_document_name = models.CharField(max_length=255, blank=True)
    action_list_document_last_updated = models.DateTimeField(null=True, blank=True)
    action_list_stage_snapshot = models.CharField(max_length=20, blank=True)
    feedback_deadline_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-created_at"]

    def __str__(self):
        who = self.member or self.email or "anonymous"
        return f"Action list feedback for {self.project.title} by {who}"

    def latest_document_label(self) -> str:
        if self.uploaded_document:
            return self.uploaded_document.name.rsplit("/", 1)[-1]
        return ""

    def snapshot_deadline(self):
        return self.feedback_deadline_at


class ReferenceSourceBatch(models.Model):
    """Represents one RIS (or similar) import event for a project."""

    SOURCE_TYPE_CHOICES = [
        ("journal_search", "Journal / database search"),
        ("grey_literature", "Grey literature search"),
        ("non_english", "Non-English search"),
        ("manual_upload", "Manual upload"),
        ("library_link", "Library link"),
        ("legacy", "Legacy import"),
    ]  # TODO: Other teams may want to drop or modify these choices. Also most likely it should be simplified to journal search or manual upload.

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="reference_batches"
    )
    label = models.CharField(
        max_length=255,
        help_text="Short identifier shown to authors (e.g. 'Scopus Jan 2023').",
    )
    source_type = models.CharField(max_length=40, choices=SOURCE_TYPE_CHOICES)
    search_date_start = models.DateField(null=True, blank=True)
    search_date_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_reference_batches",
    )
    original_filename = models.CharField(max_length=255, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    ris_sha1 = models.CharField(
        max_length=40,
        blank=True,
        help_text="SHA1 fingerprint of the original RIS payload for deduplication.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "reference batch"
        verbose_name_plural = "reference batches"

    def __str__(self):
        return f"{self.label} ({self.project.title})"


class ReferenceSourceBatchNoteHistory(models.Model):
    batch = models.ForeignKey(
        ReferenceSourceBatch,
        on_delete=models.CASCADE,
        related_name="note_history",
    )
    previous_notes = models.TextField(blank=True)
    new_notes = models.TextField(blank=True)
    changed_by = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="reference_batch_note_changes",
    )
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self):
        return f"Notes update for {self.batch} at {self.changed_at:%Y-%m-%d %H:%M}"


class LibraryImportBatch(models.Model):
    """Represents one RIS (or similar) import event into the central library."""

    SOURCE_TYPE_CHOICES = ReferenceSourceBatch.SOURCE_TYPE_CHOICES

    label = models.CharField(
        max_length=255,
        help_text="Short identifier shown to authors (e.g. 'EndNote 2018-2024').",
    )
    source_type = models.CharField(max_length=40, choices=SOURCE_TYPE_CHOICES)
    search_date_start = models.DateField(null=True, blank=True)
    search_date_end = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_library_batches",
    )
    original_filename = models.CharField(max_length=255, blank=True)
    record_count = models.PositiveIntegerField(default=0)
    ris_sha1 = models.CharField(
        max_length=40,
        blank=True,
        help_text="SHA1 fingerprint of the original RIS payload for deduplication.",
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "library batch"
        verbose_name_plural = "library batches"

    def __str__(self):
        return self.label


class LibraryReference(models.Model):
    """Canonical reference record stored in the central library."""

    import_batch = models.ForeignKey(
        LibraryImportBatch,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="references",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    hash_key = models.CharField(
        max_length=40,
        unique=True,
        help_text="HASH used to detect duplicates within the library.",
    )
    source_identifier = models.CharField(
        max_length=255,
        blank=True,
        help_text="Identifier from the source import (e.g. RefID or Accession number).",
    )
    title = models.TextField()
    abstract = models.TextField(blank=True)
    authors = models.TextField(blank=True)
    publication_year = models.PositiveIntegerField(null=True, blank=True)
    journal = models.CharField(max_length=255, blank=True)
    volume = models.CharField(max_length=50, blank=True)
    issue = models.CharField(max_length=50, blank=True)
    pages = models.CharField(max_length=50, blank=True)
    doi = models.CharField(max_length=255, blank=True)
    url = models.URLField(blank=True)
    language = models.CharField(max_length=50, blank=True)
    raw_ris = models.JSONField(
        default=dict,
        blank=True,
        help_text="Original import key/value pairs for full fidelity storage.",
    )
    raw_source = models.TextField(
        blank=True,
        help_text="Original raw record payload (e.g. EndNote XML).",
    )
    raw_source_format = models.CharField(max_length=50, blank=True)
    reference_document = models.FileField(
        upload_to="reference_documents/%Y/%m/%d",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["pdf"])],
        help_text="Optional uploaded PDF of the reference.",
    )
    reference_document_uploaded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title[:120]


class Reference(models.Model):
    """A single bibliographic record imported from a batch."""

    SCREENING_STATUS_CHOICES = [
        ("pending", "Pending"),
        ("included", "Include"),
        ("excluded", "Exclude"),
    ]
    FOLDER_CHOICES = [
        ("", "—"),
        ("1", "1. Amphibians"),
        ("2", "2. Birds"),
        ("3a", "3a. Fish - Fresh Water"),
        ("3b", "3b. Fish - Marine"),
        ("3", "3. Fish (legacy - recategorise)"),
        ("4", "4. Terrestrial invertebrates"),
        ("5", "5. Marine invertebrates"),
        ("6", "6. Mammals"),
        ("7", "7. Reptiles"),
        ("8", "8. Animals ex-situ"),
        ("9", "9. Individual plant/algae populations"),
        ("10", "10. Plants/algae ex situ"),
        ("11", "11. Fungi"),
        ("12", "12. Bacteria/other living agents"),
        ("13", "13. Coastal (plants/algae communities)"),
        ("14", "14. Farmland (plants/algae communities)"),
        ("15", "15. Forests/Woodland"),
        ("16", "16. Rivers, lakes and lagoons"),
        ("17", "17. Grassland/Savanna"),
        ("18", "18. Marine (plants/algae communities)"),
        ("19", "19. Shrubland"),
        ("20", "20. Wetlands"),
        ("21", "21. Invasive/problem amphibians"),
        ("22", "22. Invasive/problem birds"),
        ("23", "23. Invasive/problem fish"),
        ("24", "24. Invasive/problem invertebrates"),
        ("25", "25. Invasive/problem mammals"),
        ("26", "26. Invasive/problem reptiles"),
        ("27", "27. Invasive/problem plants/algae"),
        ("28", "28. Invasive/problem fungi"),
        ("29", "29. Invasive/problem bacteria/agents"),
        ("30", "30. Behaviour change"),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="references"
    )
    library_reference = models.ForeignKey(
        LibraryReference,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="project_references",
    )
    batch = models.ForeignKey(
        ReferenceSourceBatch,
        on_delete=models.CASCADE,
        related_name="references",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    hash_key = models.CharField(
        max_length=40,
        db_index=True,
        help_text="HASH used to detect duplicates within a project.",
    )
    source_identifier = models.CharField(
        max_length=255,
        blank=True,
        help_text="Identifier from the source RIS (e.g. RefID or Accession number).",
    )
    title = models.TextField()
    abstract = models.TextField(blank=True)
    authors = models.TextField(blank=True)
    publication_year = models.PositiveIntegerField(null=True, blank=True)
    journal = models.CharField(max_length=255, blank=True)
    volume = models.CharField(max_length=50, blank=True)
    issue = models.CharField(max_length=50, blank=True)
    pages = models.CharField(max_length=50, blank=True)
    doi = models.CharField(max_length=255, blank=True)
    url = models.URLField(blank=True)
    language = models.CharField(max_length=50, blank=True)
    raw_ris = models.JSONField(
        default=dict,
        blank=True,
        help_text="Original import key/value pairs for full fidelity storage.",
    )
    reference_document = models.FileField(
        upload_to="reference_documents/%Y/%m/%d",
        blank=True,
        null=True,
        validators=[FileExtensionValidator(["pdf"])],
        help_text="Optional uploaded PDF of the reference.",
    )
    reference_document_uploaded_at = models.DateTimeField(null=True, blank=True)
    screening_status = models.CharField(
        max_length=40,
        choices=SCREENING_STATUS_CHOICES,
        default="pending",
    )
    reference_folder = models.JSONField(
        default=list,
        blank=True,
        help_text="List of CE subject folders assigned to this reference.",
    )
    screening_notes = models.TextField(blank=True)
    screening_decision_at = models.DateTimeField(null=True, blank=True)
    screened_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="screened_references",
    )
    needs_help = models.BooleanField(default=False)

    class Meta:
        ordering = ["title"]
        unique_together = [("project", "hash_key")]

    def __str__(self):
        return self.title[:120]

    @property
    def canonical(self):
        return self.library_reference or self

    def mark_screened(self, status: str, user: User | None = None, notes: str = ""):
        """Convenience helper to update screening info consistently."""

        if status not in dict(self.SCREENING_STATUS_CHOICES):
            raise ValueError(f"Unknown screening status: {status}")
        self.screening_status = status
        self.screening_decision_at = timezone.now()
        if notes:
            self.screening_notes = notes
        if user:
            self.screened_by = user
        self.save(
            update_fields=[
                "screening_status",
                "screening_decision_at",
                "screening_notes",
                "screened_by",
                "updated_at",
            ]
        )


class ReferenceSummary(models.Model):
    STATUS_TODO = "todo"
    STATUS_DRAFT = "draft"
    STATUS_REVIEW = "review"
    STATUS_DONE = "done"
    STATUS_CHOICES = [
        (STATUS_TODO, "To summarise"),
        (STATUS_DRAFT, "In progress"),
        (STATUS_REVIEW, "Needs review/help"),
        (STATUS_DONE, "Summarised"),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="reference_summaries"
    )
    reference = models.ForeignKey(
        Reference, on_delete=models.CASCADE, related_name="summaries"
    )
    assigned_to = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="assigned_summaries"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_TODO)
    needs_help = models.BooleanField(default=False)
    reference_identifier = models.CharField(max_length=255, blank=True)
    summary_identifier = models.CharField(max_length=255, blank=True)
    reference_label = models.CharField(max_length=255, blank=True)
    action_description = models.CharField(max_length=255, blank=True)
    study_design = models.CharField(max_length=255, blank=True)
    study_type = models.CharField(max_length=255, blank=True)
    sites_replications = models.CharField(max_length=255, blank=True)
    year_range = models.CharField(max_length=100, blank=True)
    habitat_and_sites = models.TextField(blank=True)
    region = models.CharField(max_length=255, blank=True)
    country = models.CharField(max_length=255, blank=True)
    summary_of_results = models.TextField(blank=True)
    action_methods = models.TextField(blank=True)
    experimental_design = models.TextField(blank=True)
    site_context_details = models.TextField(blank=True)
    sampling_methods_details = models.TextField(blank=True)
    cost_summary = models.TextField(blank=True)
    outcome_rows = models.JSONField(default=list, blank=True)
    benefits_score = models.FloatField(null=True, blank=True)
    harms_score = models.FloatField(null=True, blank=True)
    reliability_score = models.FloatField(null=True, blank=True)
    relevance_score = models.FloatField(null=True, blank=True)
    summary_text = models.TextField(blank=True)
    key_findings = models.TextField(blank=True)
    synopsis_draft = models.TextField(blank=True)
    summary_author = models.CharField(max_length=255, blank=True)
    broad_category = models.CharField(max_length=255, blank=True)
    keywords = models.JSONField(default=list, blank=True)
    source_url = models.URLField(max_length=500, blank=True)
    crop_type = models.CharField(max_length=255, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_summary_model = models.CharField(max_length=255, blank=True)
    ai_summary_generated_at = models.DateTimeField(null=True, blank=True)
    action_tags = models.JSONField(default=list, blank=True)
    threat_tags = models.JSONField(default=list, blank=True)
    taxon_tags = models.JSONField(default=list, blank=True)
    habitat_tags = models.JSONField(default=list, blank=True)
    location_tags = models.JSONField(default=list, blank=True)
    research_design = models.CharField(max_length=255, blank=True)
    citation = models.CharField(max_length=512, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["reference__title", "created_at", "id"]

    @property
    def explicit_label(self):
        for value in (
            self.action_description,
            self.summary_identifier,
            self.reference_label,
        ):
            if value and value.strip():
                return value.strip()
        return ""

    @property
    def display_label(self):
        if self.explicit_label:
            return self.explicit_label
        return f"Summary #{self.pk}" if self.pk else "Summary"

    @property
    def choice_label(self):
        return f"{self.reference.canonical.title} — {self.display_label}"

    def __str__(self):
        return self.choice_label


class ReferenceSummaryComment(models.Model):
    summary = models.ForeignKey(
        ReferenceSummary, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    body = models.TextField()
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    )
    attachment = models.FileField(upload_to="summary_comments/", blank=True)
    notify_assignee = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Comment by {self.author} on {self.summary}"


class ReferenceComment(models.Model):
    reference = models.ForeignKey(
        Reference, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(User, on_delete=models.CASCADE)
    body = models.TextField()
    parent = models.ForeignKey(
        "self", on_delete=models.CASCADE, null=True, blank=True, related_name="replies"
    )
    attachment = models.FileField(upload_to="reference_comments/", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Comment by {self.author} on reference {self.reference_id}"


class ReferenceActionSummary(models.Model):
    reference_summary = models.ForeignKey(
        ReferenceSummary,
        on_delete=models.CASCADE,
        related_name="action_summaries",
    )
    action_name = models.CharField(max_length=255)
    summary_text = models.TextField()
    order = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.reference_summary.reference.canonical.title[:40]} – {self.action_name}"


class IUCNCategory(models.Model):
    KIND_THREAT = "threat"
    KIND_ACTION = "action"
    KIND_CHOICES = [
        (KIND_THREAT, "Direct threat"),
        (KIND_ACTION, "Conservation action"),
    ]

    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    code = models.CharField(max_length=20, blank=True)
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["kind", "position", "name"]
        unique_together = [("kind", "name")]

    def __str__(self):
        prefix = "Threat" if self.kind == self.KIND_THREAT else "Action"
        if self.code:
            return f"{prefix} {self.code}: {self.name}"
        return f"{prefix}: {self.name}"


class SynopsisChapter(models.Model):
    TYPE_TEXT = "text"
    TYPE_EVIDENCE = "evidence"
    TYPE_APPENDIX = "appendix"
    TYPE_CHOICES = [
        (TYPE_TEXT, "Text chapter"),
        (TYPE_EVIDENCE, "Evidence chapter"),
        (TYPE_APPENDIX, "Appendix / back matter"),
    ]

    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="synopsis_chapters"
    )
    title = models.CharField(max_length=255)
    chapter_type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default=TYPE_EVIDENCE,
    )
    background_text = models.TextField(blank=True)
    background_references = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.project.title}: {self.title}"

    @property
    def supports_evidence_structure(self):
        return self.chapter_type == self.TYPE_EVIDENCE


class SynopsisSubheading(models.Model):
    chapter = models.ForeignKey(
        SynopsisChapter, on_delete=models.CASCADE, related_name="subheadings"
    )
    title = models.CharField(max_length=255)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.chapter.title} – {self.title}"


class SynopsisIntervention(models.Model):
    EVIDENCE_STATUS_HAS_EVIDENCE = "has_evidence"
    EVIDENCE_STATUS_NO_STUDIES = "no_studies"
    EVIDENCE_STATUS_CHOICES = [
        (EVIDENCE_STATUS_HAS_EVIDENCE, "Has evidence"),
        (EVIDENCE_STATUS_NO_STUDIES, "No studies found"),
    ]

    subheading = models.ForeignKey(
        SynopsisSubheading, on_delete=models.CASCADE, related_name="interventions"
    )
    title = models.CharField(max_length=255)
    iucn_category = models.ForeignKey(
        IUCNCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="interventions",
    )
    is_cross_reference = models.BooleanField(
        default=False,
        help_text="Mark when evidence is summarized under another intervention and only referenced here.",
    )
    primary_intervention = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cross_references",
        help_text="Main intervention that contains the full evidence summary.",
    )
    background_text = models.TextField(blank=True)
    background_references = models.TextField(blank=True)
    ce_action_url = models.URLField(max_length=500, blank=True)
    evidence_status = models.CharField(
        max_length=20,
        choices=EVIDENCE_STATUS_CHOICES,
        default=EVIDENCE_STATUS_HAS_EVIDENCE,
    )
    synthesis_text = models.TextField(blank=True)
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.subheading.title} – {self.title}"


class SynopsisInterventionKeyMessage(models.Model):
    GROUP_COMMUNITY = "community"
    GROUP_POPULATION = "population"
    GROUP_BEHAVIOUR = "behaviour"
    GROUP_RESPONSE = "response"
    GROUP_CHOICES = [
        (GROUP_COMMUNITY, "Community response"),
        (GROUP_POPULATION, "Population response"),
        (GROUP_BEHAVIOUR, "Behaviour"),
        (GROUP_RESPONSE, "General response"),
    ]

    intervention = models.ForeignKey(
        SynopsisIntervention, on_delete=models.CASCADE, related_name="key_messages"
    )
    response_group = models.CharField(
        max_length=20,
        choices=GROUP_CHOICES,
        default=GROUP_RESPONSE,
    )
    outcome_label = models.CharField(max_length=255, blank=True)
    statement = models.TextField()
    study_count = models.PositiveIntegerField(null=True, blank=True)
    supporting_summaries = models.ManyToManyField(
        ReferenceSummary,
        blank=True,
        related_name="supporting_key_messages",
        help_text="Optional subset of assigned study summaries that support this key message.",
    )
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        label = self.outcome_label or "Key message"
        return f"{self.intervention.title}: {label}"


class SynopsisAssignment(models.Model):
    intervention = models.ForeignKey(
        SynopsisIntervention, on_delete=models.CASCADE, related_name="assignments"
    )
    reference_summary = models.ForeignKey(
        ReferenceSummary, on_delete=models.CASCADE, related_name="synopsis_assignments"
    )
    position = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        unique_together = [("intervention", "reference_summary")]

    def __str__(self):
        return f"{self.intervention.title} – {self.reference_summary}"


class SynopsisExportLog(models.Model):
    project = models.ForeignKey(
        Project, on_delete=models.CASCADE, related_name="synopsis_exports"
    )
    exported_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    exported_at = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True)
    archived_file = models.FileField(upload_to="synopsis_exports/", blank=True)

    class Meta:
        ordering = ["-exported_at", "id"]

    def __str__(self):
        return f"{self.project.title} export {self.exported_at:%Y-%m-%d %H:%M}"
