from django import forms
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from .models import (
    AdvisoryBoardMember,
    Funder,
    Protocol,
    UserRole,
)
from django.contrib.auth.models import Group

GLOBAL_ROLE_CHOICES = [
    ("author", "Author"),
    ("external_collaborator", "External Collaborator"),
    ("manager", "Manager"),
]


class ProtocolUpdateForm(forms.ModelForm):
    class Meta:
        model = Protocol
        fields = ["document", "stage", "text_version"]
        widgets = {
            "stage": forms.Select(attrs={"class": "form-select"}),
            "text_version": forms.Textarea(attrs={"rows": 10, "class": "form-control"}),
        }


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
    class Meta:
        model = AdvisoryBoardMember
        fields = [
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
    class Meta:
        model = Funder
        fields = [
            "organisation",
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
        return cleaned


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


class ParticipationConfirmForm(forms.Form):
    statement = forms.CharField(
        label="Participation confirmation",
        help_text="Please affirm you will participate and provide valuable input.",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "I confirm that I will actively participate and provide valuable input to this synopsis.",
            }
        ),
    )


class ProtocolFeedbackForm(forms.Form):
    content = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 6, "placeholder": "Share your comments here"}
        ),
    )
    uploaded_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["docx"])],
        help_text="Upload your annotated .docx protocol (optional).",
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
