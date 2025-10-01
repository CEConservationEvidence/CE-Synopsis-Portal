from django import forms
from django.contrib.auth.models import Group, User
from django.core.validators import FileExtensionValidator

from .models import (
    ActionList,
    AdvisoryBoardMember,
    Funder,
    Project,
    Protocol,
    Reference,
    ReferenceSourceBatch,
    UserRole,
)

# TODO: see if these are enough, if not add more titles.
FUNDER_TITLE_CHOICES = [
    ("", "Title"),
    ("Dr", "Dr"),
    ("Prof", "Prof"),
    ("Mr", "Mr"),
    ("Mrs", "Mrs"),
    ("Ms", "Ms"),
    ("Mx", "Mx"),
]

GLOBAL_ROLE_CHOICES = [
    ("author", "Author"),
    (
        "external_collaborator",
        "External Collaborator",
    ),
    ("manager", "Manager"),
]


class ProtocolUpdateForm(forms.ModelForm):
    document = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(["pdf", "docx"])],
        widget=forms.FileInput(attrs={"class": "form-control"}),
        help_text="Upload a PDF or DOCX version of the protocol.",
    )
    change_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        help_text="Explain what changed in this revision so other authors can stay aligned.",
    )

    class Meta:
        model = Protocol
        fields = ["document", "stage"]
        widgets = {
            "stage": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_change_reason(self):
        reason = self.cleaned_data.get("change_reason", "")
        return reason.strip()


class ActionListUpdateForm(forms.ModelForm):
    document = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(["pdf", "docx"])],
        widget=forms.FileInput(attrs={"class": "form-control"}),
        help_text="Upload a PDF or DOCX version of the action list.",
    )
    change_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
        help_text="Explain what changed so advisory members can follow revisions.",
    )

    class Meta:
        model = ActionList
        fields = ["document", "stage"]
        widgets = {
            "stage": forms.Select(attrs={"class": "form-select"}),
        }

    def clean_change_reason(self):
        reason = self.cleaned_data.get("change_reason", "")
        return reason.strip()


class CreateUserForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(help_text="Used as the username")
    password = forms.CharField(
        max_length=128, required=False, widget=forms.PasswordInput
    )
    global_role = forms.ChoiceField(
        choices=GLOBAL_ROLE_CHOICES, help_text="Global role (not tied to a project)"
    )


class AssignRoleForm(forms.Form):
    user = forms.ModelChoiceField(queryset=User.objects.order_by("username"))
    role = forms.ChoiceField(choices=UserRole.ROLE_CHOICES)


class AdvisoryBoardMemberForm(forms.ModelForm):
    title = forms.ChoiceField(
        choices=FUNDER_TITLE_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Title",
    )

    class Meta:
        model = AdvisoryBoardMember
        fields = [
            "title",
            "first_name",
            "middle_name",
            "last_name",
            "organisation",
            "email",
            "location",
            "continent",
            "notes",
        ]
        widgets = {
            "title": forms.Select(attrs={"class": "form-select"}),
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "middle_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "organisation": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "location": forms.TextInput(attrs={"class": "form-control"}),
            "continent": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }


class AdvisoryInviteForm(forms.Form):
    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": "form-control"}))
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Optional response deadline to show in the email.",
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        help_text="Optional personal note to include.",
    )
    include_protocol = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Include the current protocol in this email.",
    )
    protocol_content = forms.ChoiceField(
        required=False,
        choices=[("file", "Attach link to file"), ("text", "Embed rich text version")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class AssignAuthorsForm(forms.Form):
    authors = forms.ModelMultipleChoiceField(
        queryset=User.objects.order_by("username"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 8}),
        help_text="Select users to assign as authors for this project.",
    )


class FunderForm(forms.ModelForm):
    contact_title = forms.ChoiceField(
        choices=FUNDER_TITLE_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Title",
    )

    class Meta:
        model = Funder
        fields = [
            "organisation",
            "contact_title",
            "contact_first_name",
            "contact_last_name",
            "funds_allocated",
            "fund_start_date",
            "fund_end_date",
        ]
        widgets = {
            "organisation": forms.TextInput(attrs={"class": "form-control"}),
            "contact_first_name": forms.TextInput(attrs={"class": "form-control"}),
            "contact_last_name": forms.TextInput(attrs={"class": "form-control"}),
            "funds_allocated": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01"}
            ),
            "fund_start_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
            "fund_end_date": forms.DateInput(
                attrs={"type": "date", "class": "form-control"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.required = False

    def has_identity_fields(self) -> bool:
        cleaned = getattr(self, "cleaned_data", {})
        return any(
            cleaned.get(key)
            for key in ("organisation", "contact_first_name", "contact_last_name")
        )

    def has_meaningful_input(self) -> bool:
        cleaned = getattr(self, "cleaned_data", {})
        return any(
            cleaned.get(key)
            for key in (
                "organisation",
                "contact_title",
                "contact_first_name",
                "contact_last_name",
                "funds_allocated",
                "fund_start_date",
                "fund_end_date",
            )
        )

    def clean(self):
        cleaned = super().clean()
        if self.has_meaningful_input() and not self.has_identity_fields():
            raise forms.ValidationError(
                "Provide an organisation or a contact first/last name for the funder."
            )

        start = cleaned.get("fund_start_date")
        end = cleaned.get("fund_end_date")
        if start and end and start > end:
            message = "Start date cannot be after the end date."
            self.add_error("fund_start_date", message)
            self.add_error("fund_end_date", message)
            raise forms.ValidationError(message)
        return cleaned


class ProjectDeleteForm(forms.Form):
    confirm_title = forms.CharField(
        label="Confirm title",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Type the synopsis title to confirm",
                "autocomplete": "off",
            }
        ),
    )
    acknowledge_irreversible = forms.BooleanField(
        label="I understand this action permanently deletes the synopsis and all related records.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, project: Project | None = None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        if project:
            self.fields["confirm_title"].help_text = (
                f"Enter '{project.title}' to enable deletion."
            )

    def clean_confirm_title(self):
        value = self.cleaned_data.get("confirm_title", "").strip()
        if self.project and value != self.project.title:
            raise forms.ValidationError("Title does not match this synopsis.")
        return value


class ProjectSettingsForm(forms.ModelForm):
    class Meta:
        model = Project
        fields = ["title"]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
        }
        error_messages = {
            "title": {
                "required": "Enter a title for the synopsis.",
            }
        }

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise forms.ValidationError("Enter a title for the synopsis.")
        return title

class AdvisoryBulkInviteForm(forms.Form):
    due_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Optional response deadline to show in the email.",
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        help_text="Optional personal note to include.",
    )
    include_protocol = forms.BooleanField(
        required=False,
        initial=False,
        help_text="Include the current protocol in this email.",
    )
    protocol_content = forms.ChoiceField(
        required=False,
        choices=[("file", "Attach link to file"), ("text", "Embed rich text version")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )


class ProtocolSendForm(forms.Form):
    content = forms.ChoiceField(
        choices=[("file", "Send file link"), ("text", "Send embedded rich text")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        help_text="Optional personal note to include.",
    )


class ActionListSendForm(forms.Form):
    content = forms.ChoiceField(
        choices=[("file", "Send file link"), ("text", "Send embedded rich text")],
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    message = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        help_text="Optional personal note to include.",
    )


class ReminderScheduleForm(forms.Form):
    reminder_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Members without invitations will get this response deadline set.",
    )


class ProtocolReminderScheduleForm(forms.Form):
    deadline = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="Set or update the protocol feedback deadline (date and time) for members with the protocol.",
    )


class ActionListReminderScheduleForm(forms.Form):
    deadline = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="Set or update the action list feedback deadline (date and time) for members.",
    )


class ParticipationConfirmForm(forms.Form):
    confirm_participation = forms.BooleanField(
        label="I agree to actively participate in the development of this synopsis",
        help_text="Please tick this box to confirm your commitment.",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    statement = forms.CharField(
        required=False,
        label="Optional note",
        help_text="Share any context or expectations you have for your participation (optional).",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Optional: add any notes about your availability or expectations.",
            }
        ),
    )


class ProtocolFeedbackForm(forms.Form):
    content = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": "Share your comments here",
            }
        ),
    )
    uploaded_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["docx"])],
        help_text="Upload your annotated .docx protocol (optional).",
    )


class ActionListFeedbackForm(forms.Form):
    content = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": "Share your comments on the action list here",
            }
        ),
    )
    uploaded_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["docx"])],
        help_text="Upload your annotated .docx action list (optional).",
    )


class ProtocolFeedbackCloseForm(forms.Form):
    message = forms.CharField(
        required=False,
        label="Message to advisory board",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Optional note shared with advisory members when feedback closes.",
            }
        ),
        help_text="Shown to advisory board members when they open an existing feedback link.",
    )


# TODO: cleanup this form, add more validation and error handling (file types supported are currently .RIS but .txt is also being used by team).
class ReferenceBatchUploadForm(forms.Form):
    label = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        help_text="Short name shown to the team (e.g. 'Scopus Jan 2023').",
    )
    source_type = forms.ChoiceField(
        choices=ReferenceSourceBatch.SOURCE_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        help_text="What kind of search produced this file?",
    )
    search_date = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Date the search was run (optional). This means the actual date the search was run or received by Kate, not the dates interval for the search.",
    )
    ris_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["ris", "txt"])],
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        help_text="Internal notes about this batch (optional).",
    )


class ReferenceScreeningForm(forms.Form):
    reference_id = forms.IntegerField(widget=forms.HiddenInput)
    screening_status = forms.ChoiceField(
        choices=Reference.SCREENING_STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    screening_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 2,
                "placeholder": "Notes on inclusion/exclusion (optional)",
            }
        ),
    )


class ActionListFeedbackCloseForm(forms.Form):
    message = forms.CharField(
        required=False,
        label="Message to advisory board",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Share closing notes about the action list (optional)",
            }
        ),
        help_text="Optional message to send when action list feedback is closed.",
    )
