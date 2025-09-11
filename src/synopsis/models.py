from django.db import models
from django.contrib.auth.models import User

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
