from django import forms
from .models import Protocol


class ProtocolUpdateForm(forms.ModelForm):
    class Meta:
        model = Protocol
        fields = ["document", "text_version"]
        widgets = {"text_version": forms.Textarea(attrs={"rows": 6})}


class CreateUserForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    password = forms.CharField(
        max_length=128, required=False, widget=forms.PasswordInput
    )
