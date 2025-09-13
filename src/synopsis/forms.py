from django import forms
from django.contrib.auth.models import User
from .models import Protocol, UserRole  # keep for now (project roles)
from django.contrib.auth.models import Group

GLOBAL_ROLE_CHOICES = [
    ("author", "Author"),
    ("external_collaborator", "External Collaborator"),
    ("manager", "Manager"),
]


class ProtocolUpdateForm(forms.ModelForm):
    class Meta:
        model = Protocol
        fields = ["document", "text_version"]
        widgets = {"text_version": forms.Textarea(attrs={"rows": 6})}


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
