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
            "External Collaborator",  # outside the core team, with limited access and permissions.
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
    fund_start_date = models.DateField(null=True, blank=True)
    fund_end_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.project.title})"


class Protocol(models.Model):
    """The protocol document for a project, drafted by an author and finalized by manager."""

    project = models.OneToOneField(
        Project, on_delete=models.CASCADE, related_name="protocol"
    )
    document = models.FileField(upload_to="protocols/")
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    text_version = models.TextField(blank=True)

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
    last_name = models.CharField(max_length=100, blank=True)
    organisation = models.CharField(max_length=255, blank=True)
    email = models.EmailField()
    location = models.CharField(max_length=100, blank=True)
    continent = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)

    # Invitation & communication tracking
    invite_sent = models.BooleanField(default=False)
    response_date = models.DateField(null=True, blank=True)
    response = models.CharField(
        max_length=100, blank=True
    )  # e.g. "accepted", "declined", etc.
    feedback_on_list = models.BooleanField(default=False)
    feedback_on_actions_received = models.BooleanField(default=False)
    wm_replied = models.BooleanField(default=False)  # TODO: What is wm? Clarify.
    feedback_added_to_action_list = models.BooleanField(default=False)
    reminder_sent = models.BooleanField(default=False)

    # Protocol interaction
    sent_protocol = models.BooleanField(default=False)
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
    email = models.EmailField()
    invited_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    accepted = models.BooleanField(default=False)
    responded_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Invite to {self.email} for {self.project.title}"
