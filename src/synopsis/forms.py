import re

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.core.validators import FileExtensionValidator
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.utils import timezone
from django.utils.text import slugify

from .utils import (
    default_advisory_invitation_message,
    minimum_allowed_deadline_date,
)

MAX_LOCATION_LINE_LENGTH = 200


def _advisory_invite_response_window_days():
    return getattr(settings, "ADVISORY_INVITE_RESPONSE_WINDOW_DAYS", 10)


def _advisory_document_feedback_window_days():
    return getattr(settings, "ADVISORY_DOCUMENT_FEEDBACK_WINDOW_DAYS", 10)


def _minimum_allowed_deadline_date_str():
    return minimum_allowed_deadline_date().isoformat()


def _minimum_allowed_deadline_datetime_local_str():
    return f"{minimum_allowed_deadline_date().isoformat()}T00:00"


def _set_min_date_attr(field):
    field.widget.attrs["min"] = _minimum_allowed_deadline_date_str()


def _set_min_datetime_attr(field):
    field.widget.attrs["min"] = _minimum_allowed_deadline_datetime_local_str()


def _validate_not_same_day_date(value, field_label):
    if not value:
        return value
    minimum_date = minimum_allowed_deadline_date()
    if value < minimum_date:
        raise forms.ValidationError(
            f"{field_label} must be at least one day in the future."
        )
    return value


def _validate_not_same_day_datetime(value, field_label):
    if not value:
        return value
    try:
        local_value = timezone.localtime(value)
    except (ValueError, TypeError):
        local_value = value
    minimum_date = minimum_allowed_deadline_date()
    if local_value.date() < minimum_date:
        raise forms.ValidationError(
            f"{field_label} must be at least one day in the future."
        )
    return value

from .models import (
    ActionList,
    AdvisoryBoardMember,
    AdvisoryBoardCustomField,
    Funder,
    FunderContact,
    Project,
    Protocol,
    Reference,
    LibraryReference,
    ReferenceSummary,
    ReferenceSourceBatch,
    ReferenceActionSummary,
    IUCNCategory,
    SynopsisChapter,
    SynopsisIntervention,
    SynopsisInterventionKeyMessage,
    UserRole,
)

RESEARCH_DESIGN_CHOICES = [
    ("", "Choose"),
    ("Replicated", "Replicated"),
    ("Randomized", "Randomized"),
    ("Paired sites", "Paired sites"),
    ("Controlled*", "Controlled*"),
    ("Before-and-after", "Before-and-after"),
    ("Site comparison*", "Site comparison*"),
    ("Review", "Review"),
    ("Systematic review", "Systematic review"),
    ("Study", "Study"),
]

IUCN_ACTION_TAGS = [
    "Land/water protection-Area protection",
    "Land/water protection-Site/area stewardship",
    "Land/water management-Site/area management",
    "Land/water management-Invasive/problematic species control",
    "Land/water management-Habitat & natural process restoration",
    "Land/water management-Natural process regeneration",
    "Species management-Species recovery",
    "Species management-Species re-introduction",
    "Species management-Ex situ conservation",
    "Species management-Conservation translocation",
    "Species management-Disease/pathogen treatment",
    "Species management-Biological resource use management",
    "Education & awareness-Formal education",
    "Education & awareness-Training",
    "Education & awareness-Awareness & communications",
    "Law & policy-Legislation",
    "Law & policy-Regulations",
    "Law & policy-Incentives",
    "Law & policy-Private sector standards & codes",
    "Law & policy-Policies & regulations",
    "Law & policy-Law enforcement & prosecution",
    "Livelihood, economic & other incentives-Linked enterprises & livelihood alternatives",
    "Livelihood, economic & other incentives-Incentives/subsidies",
    "Livelihood, economic & other incentives-Market forces",
    "Livelihood, economic & other incentives-Conservation payments",
    "Livelihood, economic & other incentives-Non-monetary values",
    "External capacity building-Institutional development",
    "External capacity building-Alliance & partnership development",
    "External capacity building-Conservation finance",
    "External capacity building-Capacity building",
    "External capacity building-Technology transfer",
    "Research & monitoring-Basic research & status monitoring",
    "Research & monitoring-Resource & habitat management",
    "Research & monitoring-Species management",
    "Research & monitoring-Socio-economics",
    "Research & monitoring-Conservation planning",
    "Research & monitoring-Other",
]

IUCN_ACTION_CHOICES = [(tag, tag) for tag in IUCN_ACTION_TAGS]

IUCN_THREAT_TAGS = [
    "Residential & commercial development-Housing/urban areas",
    "Residential & commercial development-Commercial/industrial areas",
    "Residential & commercial development-Tourism/recreation areas",
    "Agriculture & aquaculture-Annual/perennial non-timber crops",
    "Agriculture & aquaculture-Wood/pulp plantations",
    "Agriculture & aquaculture-Livestock farm/ranch",
    "Agriculture & aquaculture-Marine & freshwater aquaculture",
    "Energy production & mining-Oil/gas drilling",
    "Energy production & mining-Mining/quarrying",
    "Energy production & mining-Renewable energy",
    "Transportation & service corridors-Roads/railroads",
    "Transportation & service corridors-Utility/service lines",
    "Transportation & service corridors-Shipping lanes",
    "Transportation & service corridors-Flight paths",
    "Biological resource use-Hunting/trap terrestrial animals",
    "Biological resource use-Gathering terrestrial plants",
    "Biological resource use-Logging/wood harvesting",
    "Biological resource use-Harvest aquatic resource",
    "Human intrusions & disturbance-Recreational activities",
    "Human intrusions & disturbance-War, civil unrest & military exercises",
    "Human intrusions & disturbance-Work & other activities",
    "Natural system modifications-Fire/suppression",
    "Natural system modifications-Water management/use",
    "Natural system modifications-Other ecosystem modifications",
    "Invasive & other problematic species & genes",
    "Invasive & other problematic species & genes-Problematic native species",
    "Invasive & other problematic species & genes-Introduced genetic material",
    "Pollution-Domestic/urban wastewater",
    "Pollution-Industrial/military effluents",
    "Pollution-Agric/forestry effluents",
    "Pollution-Garbage & solid waste",
    "Pollution-Air-borne pollutants",
    "Pollution-Excess energy",
    "Geological events-Volcanoes",
    "Geological events-Earthquakes/tsunamis",
    "Geological events-Avalanches/landslides",
    "Climate change & severe weather-Habitat shifting & alteration",
    "Climate change & severe weather-Droughts",
    "Climate change & severe weather-Temperature extremes",
    "Climate change & severe weather-Storms/flooding",
    "Climate change & severe weather-Other impacts",
]

IUCN_THREAT_CHOICES = [(tag, tag) for tag in IUCN_THREAT_TAGS]

IUCN_HABITAT_CHOICES = [
    ("Forest", "Forest"),
    ("Savanna", "Savanna"),
    ("Shrubland", "Shrubland"),
    ("Grassland", "Grassland"),
    ("Wetlands (inland)", "Wetlands (inland)"),
    ("Rocky areas", "Rocky areas"),
    ("Caves & subterranean", "Caves & subterranean"),
    ("Marine neritic", "Marine neritic"),
    ("Marine oceanic", "Marine oceanic"),
    ("Marine deep ocean floor", "Marine deep ocean floor"),
    ("Marine intertidal", "Marine intertidal"),
    ("Coastal wetlands", "Coastal wetlands"),
    ("Anthropogenic terrestrial", "Anthropogenic terrestrial"),
    ("Introduced vegetation", "Introduced vegetation"),
]

class TagCommaField(forms.CharField):
    """Render list-like values as comma-separated strings and back."""

    def prepare_value(self, value):
        if not value or value == "[]":
            return ""
        if isinstance(value, list):
            return ", ".join([str(v).strip() for v in value if str(v).strip()])
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed.startswith("[") and trimmed.endswith("]"):
                trimmed = trimmed[1:-1]
            return trimmed
        return str(value)


class LocationListField(forms.CharField):
    """Render list-like location values as newline-separated entries."""

    def prepare_value(self, value):
        if not value or value == "[]":
            return ""
        if isinstance(value, list):
            return "\n".join([str(v).strip() for v in value if str(v).strip()])
        return str(value)

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

# TODO: #35 Currently, the ProtocolUpdateForm and ActionListUpdateForm are very similar and could potentially be refactored to reduce redundancy. Also, additional validation and error handling could be added to enhance robustness.
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
    version_label = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g., v1.2 – Methods update"}
        ),
        help_text="Optional short tag that will appear next to the document in emails and revision history.",
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

    def clean_version_label(self):
        label = self.cleaned_data.get("version_label", "")
        return label.strip()


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
    version_label = forms.CharField(
        required=False,
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "e.g., Tasks v3 – May review"}
        ),
        help_text="Optional short tag that will appear in emails and the revision log.",
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

    def clean_version_label(self):
        label = self.cleaned_data.get("version_label", "")
        return label.strip()


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
            "country",
            "continent",
            "notes",
        ]
        widgets = {
            "first_name": forms.TextInput(attrs={"class": "form-control"}),
            "middle_name": forms.TextInput(attrs={"class": "form-control"}),
            "last_name": forms.TextInput(attrs={"class": "form-control"}),
            "organisation": forms.TextInput(attrs={"class": "form-control"}),
            "email": forms.EmailInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "continent": forms.TextInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Always capture core identity information when creating or editing a member.
        for field_name in ("first_name", "last_name", "email"):
            self.fields[field_name].required = True
        self.fields["first_name"].widget.attrs["autofocus"] = True
        placeholders = {
            "first_name": "First name (required)",
            "middle_name": "Middle name (optional)",
            "last_name": "Last name (required)",
            "organisation": "Organisation (optional)",
            "email": "Email address (required)",
            "country": "Country (optional)",
            "continent": "Continent (optional)",
            "notes": "Notes for this member (optional)",
        }
        for field_name, placeholder in placeholders.items():
            self.fields[field_name].widget.attrs["placeholder"] = placeholder


class ParticipationDeclineForm(forms.Form):
    reason = forms.CharField(
        required=False,
        max_length=200,
        label="Reason for declining (optional)",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Let us know why you’re declining. This helps us plan next steps (200 characters max).",
                "maxlength": 200,
            }
        ),
    )


class AdvisoryInviteForm(forms.Form):
    email = forms.EmailField(
        label="Recipient email",
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )
    due_date = forms.DateField(
        required=False,
        label="Response due date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="",
    )
    standard_message = forms.CharField(
        required=False,
        label="Standard invitation message",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Standard message used for advisory invitation emails",
            }
        ),
        help_text="",
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the default invitation copy.",
    )
    include_action_list = forms.BooleanField(
        required=False,
        initial=False,
        label="Attach action list document",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Optional. Adds a link to the latest action list file.",
    )
    include_collaborative_link = forms.BooleanField(
        required=False,
        initial=False,
        label="Include collaborative editor link",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Optional. Shares the live OnlyOffice editor for the action list.",
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        _set_min_date_attr(self.fields["due_date"])
        self.fields["due_date"].help_text = (
            "This date is shown in the invitation and on the advisory board dashboard. "
            f"Defaults to {_advisory_invite_response_window_days()} days from today."
        )
        standard_message = (
            getattr(project, "advisory_invitation_message", "").strip()
            if project
            else ""
        )
        if not self.is_bound:
            self.fields["standard_message"].initial = (
                standard_message or default_advisory_invitation_message()
            )
        self.fields["standard_message"].help_text = (
            "Saved as the standard invitation text for this synopsis. "
            "If unchanged, the built-in default message is used."
        )

    def clean_due_date(self):
        return _validate_not_same_day_date(
            self.cleaned_data.get("due_date"), "Response due date"
        )


class AdvisoryCustomFieldForm(forms.ModelForm):
    class Meta:
        model = AdvisoryBoardCustomField
        fields = [
            "name",
            "data_type",
            "display_group",
            "description",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "data_type": forms.Select(attrs={"class": "form-select"}),
            "display_group": forms.Select(attrs={"class": "form-select"}),
            "description": forms.TextInput(attrs={"class": "form-control"}),
        }

    def __init__(self, project, *args, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if not name:
            raise forms.ValidationError("Name is required.")
        slug = slugify(name) or "field"
        qs = AdvisoryBoardCustomField.objects.filter(project=self.project, slug=slug)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError(
                "A column with this name already exists for this project."
            )
        return name

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.project = self.project
        if commit:
            instance.save()
        return instance


class AdvisoryCustomFieldPlacementForm(forms.Form):
    display_group = forms.ChoiceField(
        choices=AdvisoryBoardCustomField.DISPLAY_GROUP_CHOICES,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
        label="Show in section",
    )


class AdvisoryMemberCustomDataForm(forms.Form):
    def __init__(
        self,
        custom_fields,
        member_status,
        initial_values,
        *args,
        form_id=None,
        **kwargs,
    ):
        self.custom_fields = list(custom_fields)
        self.member_status = member_status
        self.initial_values = initial_values or {}
        self.form_id = form_id
        super().__init__(*args, **kwargs)

        for field in self.custom_fields:
            if not field.applies_to(member_status):
                continue
            key = self._field_key(field)
            form_field = self._build_form_field(field)
            form_field.label = field.name
            if field.description:
                form_field.help_text = field.description
            form_field.required = field.is_required
            self.fields[key] = form_field
            stored_value = self.initial_values.get(field.id)
            if stored_value not in (None, ""):
                try:
                    self.initial[key] = field.parse_value(stored_value)
                except Exception:
                    self.initial[key] = stored_value

    @staticmethod
    def _field_key(field):
        return f"field_{field.id}"

    def _build_form_field(self, field: AdvisoryBoardCustomField):
        text_attrs = {"class": "form-control form-control-sm"}
        if self.form_id:
            text_attrs["form"] = self.form_id

        if field.data_type == AdvisoryBoardCustomField.TYPE_INTEGER:
            return forms.IntegerField(
                required=False, widget=forms.NumberInput(attrs=text_attrs.copy())
            )
        if field.data_type == AdvisoryBoardCustomField.TYPE_BOOLEAN:
            checkbox_attrs = {"class": "form-check-input"}
            if self.form_id:
                checkbox_attrs["form"] = self.form_id
            return forms.BooleanField(
                required=False, widget=forms.CheckboxInput(attrs=checkbox_attrs)
            )
        if field.data_type == AdvisoryBoardCustomField.TYPE_DATE:
            date_attrs = text_attrs.copy()
            date_attrs["type"] = "date"
            return forms.DateField(
                required=False, widget=forms.DateInput(attrs=date_attrs)
            )
        return forms.CharField(required=False, widget=forms.TextInput(attrs=text_attrs))

    def iter_fields(self):
        for field in self.custom_fields:
            key = self._field_key(field)
            bound = self.fields.get(key)
            if bound:
                yield field, self[key]

    def cleaned_value(self, field):
        key = self._field_key(field)
        return self.cleaned_data.get(key)

    def apply_widget_configuration(self):
        for bound in self:
            widget = bound.field.widget
            css = widget.attrs.get("class", "")
            if not css:
                if isinstance(widget, forms.CheckboxInput):
                    css = "form-check-input"
                else:
                    css = "form-control form-control-sm"
                widget.attrs["class"] = css
            if self.form_id and not widget.attrs.get("form"):
                widget.attrs["form"] = self.form_id
            if bound.errors and "is-invalid" not in widget.attrs.get("class", ""):
                widget.attrs["class"] = f"{widget.attrs['class']} is-invalid".strip()


class SynopsisChapterForm(forms.Form):
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Chapter title"}),
        label="Chapter title",
    )
    chapter_type = forms.ChoiceField(
        choices=SynopsisChapter.TYPE_CHOICES,
        initial=SynopsisChapter.TYPE_EVIDENCE,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Chapter type",
    )

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()


class SynopsisSubheadingForm(forms.Form):
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Intervention group (e.g. Oil and gas drilling)",
            }
        ),
        label="Intervention group (subheading)",
    )

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()


class SynopsisInterventionForm(forms.Form):
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Intervention"}),
        label="Intervention",
    )
    iucn_category = forms.ModelChoiceField(
        queryset=IUCNCategory.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="IUCN category",
    )
    is_cross_reference = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Cross-reference only",
    )
    primary_intervention = forms.ModelChoiceField(
        queryset=SynopsisIntervention.objects.none(),
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Primary intervention",
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["iucn_category"].queryset = IUCNCategory.objects.filter(
            kind=IUCNCategory.KIND_ACTION,
            is_active=True,
        ).order_by("position", "name")
        self.fields["iucn_category"].label_from_instance = lambda obj: obj.name
        interventions = SynopsisIntervention.objects.none()
        if project:
            interventions = (
                SynopsisIntervention.objects.filter(
                    subheading__chapter__project=project
                )
                .select_related("subheading__chapter")
                .order_by("title")
            )
        self.fields["primary_intervention"].queryset = interventions

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()

    def clean(self):
        cleaned = super().clean()
        is_cross_ref = cleaned.get("is_cross_reference")
        primary = cleaned.get("primary_intervention")
        if is_cross_ref and not primary:
            self.add_error(
                "primary_intervention",
                "Select the main intervention that holds the full evidence summary.",
            )
        if primary and not is_cross_ref:
            cleaned["is_cross_reference"] = True
        return cleaned


class SynopsisBackgroundForm(forms.Form):
    background_text = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Brief background (<200 words): description, context, related literature/harms.",
            }
        ),
        label="Background",
    )
    background_references = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Background references (one per line, published before search end date).",
            }
        ),
        label="Background references",
    )


class SynopsisInterventionSynthesisForm(forms.Form):
    ce_action_url = forms.URLField(
        required=False,
        widget=forms.URLInput(
            attrs={
                "class": "form-control",
                "placeholder": "https://www.conservationevidence.com/actions/...",
            }
        ),
        label="Conservation Evidence action URL",
    )
    evidence_status = forms.ChoiceField(
        choices=SynopsisIntervention.EVIDENCE_STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Evidence status",
    )
    synthesis_text = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Intervention-level evidence synthesis text used in compilation/export.",
            }
        ),
        label="Synthesis text",
    )


class SynopsisKeyMessageForm(forms.Form):
    response_group = forms.ChoiceField(
        choices=SynopsisInterventionKeyMessage.GROUP_CHOICES,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
        label="Response group",
    )
    outcome_label = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control form-control-sm", "placeholder": "Outcome label"}
        ),
        label="Outcome label",
    )
    study_count = forms.IntegerField(
        required=False,
        min_value=0,
        widget=forms.NumberInput(
            attrs={"class": "form-control form-control-sm", "placeholder": "Study count"}
        ),
        label="Study count",
    )
    statement = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control form-control-sm",
                "rows": 3,
                "placeholder": "Key message statement.",
            }
        ),
        label="Statement",
    )
    supporting_summaries = forms.ModelMultipleChoiceField(
        queryset=ReferenceSummary.objects.none(),
        required=False,
        widget=forms.SelectMultiple(
            attrs={"class": "form-select form-select-sm", "size": 5}
        ),
        label="Supporting studies",
    )

    def __init__(self, *args, intervention=None, **kwargs):
        super().__init__(*args, **kwargs)
        queryset = ReferenceSummary.objects.none()
        if intervention is not None:
            queryset = (
                ReferenceSummary.objects.filter(
                    synopsis_assignments__intervention=intervention
                )
                .select_related("reference")
                .order_by("synopsis_assignments__position", "reference__title")
                .distinct()
            )
        self.fields["supporting_summaries"].queryset = queryset
        self.fields["supporting_summaries"].label_from_instance = (
            lambda summary: summary.choice_label
        )

    def clean_outcome_label(self):
        return (self.cleaned_data.get("outcome_label") or "").strip()

    def clean_statement(self):
        return (self.cleaned_data.get("statement") or "").strip()


class SynopsisAssignmentForm(forms.Form):
    summary = forms.ModelChoiceField(
        queryset=ReferenceSummary.objects.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Reference summary",
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        qs = ReferenceSummary.objects.none()
        if project:
            qs = project.reference_summaries.select_related("reference").order_by(
                "reference__title", "created_at", "id"
            )
        self.fields["summary"].queryset = qs
        self.fields["summary"].label_from_instance = lambda summary: summary.choice_label

class AssignAuthorsForm(forms.Form):
    authors = forms.ModelMultipleChoiceField(
        queryset=User.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "form-check-input"}
        ),
        label="Synopsis authors",
        help_text="Select the users who should be included as authors for this synopsis.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["authors"].queryset = User.objects.order_by(
            "first_name", "last_name", "username"
        )
        self.fields["authors"].label_from_instance = self._author_label

    @staticmethod
    def _author_label(user):
        full_name = user.get_full_name().strip()
        if full_name and user.username:
            return f"{full_name} ({user.username})"
        return full_name or user.username or str(user.pk)


class FunderForm(forms.ModelForm):
    class Meta:
        model = Funder
        fields = [
            "organisation",
            "organisation_details",
            "funds_allocated",
            "fund_start_date",
            "fund_end_date",
        ]
        widgets = {
            "organisation": forms.TextInput(attrs={"class": "form-control"}),
            "organisation_details": forms.Textarea(
                attrs={"class": "form-control", "rows": 3, "placeholder": "Optional organisation notes"}
            ),
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
        return bool(cleaned.get("organisation"))

    def has_meaningful_input(self) -> bool:
        cleaned = getattr(self, "cleaned_data", {})
        return any(
            cleaned.get(key)
            for key in (
                "organisation",
                "organisation_details",
                "funds_allocated",
                "fund_start_date",
                "fund_end_date",
            )
        )

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("fund_start_date")
        end = cleaned.get("fund_end_date")
        if cleaned.get("organisation_details"):
            cleaned["organisation_details"] = cleaned.get("organisation_details", "").strip()
        if cleaned.get("organisation"):
            cleaned["organisation"] = cleaned.get("organisation", "").strip()
        if start and end and start > end:
            message = "Start date cannot be after the end date."
            self.add_error("fund_start_date", message)
            self.add_error("fund_end_date", message)
            raise forms.ValidationError(message)
        return cleaned


class FunderContactForm(forms.ModelForm):
    title = forms.ChoiceField(
        choices=FUNDER_TITLE_CHOICES,
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Title",
    )

    class Meta:
        model = FunderContact
        fields = ["title", "first_name", "last_name", "phone", "email", "is_primary"]
        widgets = {
            "first_name": forms.TextInput(
                attrs={"class": "form-control", "style": "width: 110%; min-width: 0;"}
            ),
            "last_name": forms.TextInput(
                attrs={"class": "form-control", "style": "width: 110%; min-width: 0;"}
            ),
            "phone": forms.TextInput(
                attrs={"class": "form-control", "style": "width: 110%; min-width: 0;"}
            ),
            "email": forms.EmailInput(
                attrs={"class": "form-control", "style": "width: 110%; min-width: 0;"}
            ),
            "is_primary": forms.CheckboxInput(
                attrs={"class": "form-check-input ms-1 me-1"}
            ),
            "title": forms.Select(
                attrs={"class": "form-select", "style": "width: 110%; min-width: 0;"}
            ),
        }

    def has_contact_data(self, cleaned: dict | None = None) -> bool:
        data = cleaned or getattr(self, "cleaned_data", {}) or {}
        return any(data.get(key) for key in ("first_name", "last_name", "email", "phone"))

    def clean(self):
        cleaned = super().clean()
        if self.cleaned_data.get("DELETE"):
            return cleaned
        if not self.has_contact_data(cleaned):
            # Ignore empty rows; also clear any stray primary flag so it doesn't block save
            cleaned["is_primary"] = False
            return cleaned
        return cleaned


class BaseFunderContactFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        primary_count = 0
        has_contacts = False
        first_contact_form = None
        for form in self.forms:
            if not hasattr(form, "cleaned_data"):
                continue
            if form.cleaned_data.get("DELETE"):
                continue
            if not getattr(form, "has_contact_data", lambda *_: False)(
                form.cleaned_data
            ):
                continue
            has_contacts = True
            if first_contact_form is None:
                first_contact_form = form
            if form.cleaned_data.get("is_primary"):
                primary_count += 1
        if has_contacts and primary_count == 0 and first_contact_form:
            # Auto-promote the first contact to primary if none selected
            first_contact_form.cleaned_data["is_primary"] = True
            first_contact_form.instance.is_primary = True
        if primary_count > 1:
            raise forms.ValidationError("Only one contact can be marked as primary.")


FunderContactFormSet = inlineformset_factory(
    Funder,
    FunderContact,
    form=FunderContactForm,
    formset=BaseFunderContactFormSet,
    extra=0,
    can_delete=True,
)


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
    def __init__(self, *args, project: Project | None = None, **kwargs):
        self.project = project
        super().__init__(*args, **kwargs)
        title_field = self.fields.get("title")
        if title_field:
            placeholder = "Currently: {}".format(project.title) if project else ""
            if placeholder:
                title_field.widget.attrs.setdefault("placeholder", placeholder)

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
        label="Response due date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="",
    )
    standard_message = forms.CharField(
        required=False,
        label="Standard invitation message",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Standard message used for advisory invitation emails",
            }
        ),
        help_text="",
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the default invitation copy.",
    )
    include_action_list = forms.BooleanField(
        required=False,
        initial=False,
        label="Attach action list document",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Optional. Adds a link to the latest action list file.",
    )
    include_collaborative_link = forms.BooleanField(
        required=False,
        initial=False,
        label="Include collaborative editor link",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Optional. Shares the live OnlyOffice editor for the action list.",
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        _set_min_date_attr(self.fields["due_date"])
        self.fields["due_date"].help_text = (
            "Defaults to "
            f"{_advisory_invite_response_window_days()} days from today for members "
            "without an existing deadline."
        )
        standard_message = (
            getattr(project, "advisory_invitation_message", "").strip()
            if project
            else ""
        )
        if not self.is_bound:
            self.fields["standard_message"].initial = (
                standard_message or default_advisory_invitation_message()
            )
        self.fields["standard_message"].help_text = (
            "Saved as the standard invitation text for this synopsis. "
            "If unchanged, the built-in default message is used."
        )

    def clean_due_date(self):
        return _validate_not_same_day_date(
            self.cleaned_data.get("due_date"), "Response due date"
        )


class ProtocolSendForm(forms.Form):
    due_date = forms.DateField(
        required=False,
        label="Response due date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="",
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the default invitation copy.",
    )
    include_protocol_document = forms.BooleanField(
        required=False,
        initial=False,
        label="Attach protocol document",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Required: select this or the collaborative editor link before sending.",
    )
    include_collaborative_link = forms.BooleanField(
        required=False,
        initial=False,
        label="Include collaborative editor link",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Required: select this or the protocol document before sending.",
    )

    def __init__(
        self, *args, collaborative_enabled=False, document_available=False, **kwargs
    ):
        super().__init__(*args, **kwargs)
        _set_min_date_attr(self.fields["due_date"])
        self.fields["due_date"].help_text = (
            "Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today if no "
            "deadline is already set."
        )
        self.document_available = document_available
        self.collaborative_available = collaborative_enabled
        doc_field = self.fields["include_protocol_document"]
        if document_available:
            doc_field.disabled = False
            doc_field.help_text = (
                "Required: select this or the collaborative editor link before sending."
            )
        else:
            doc_field.initial = False
            doc_field.disabled = True
            doc_field.help_text = "Upload a protocol document to include it here."

        collab_field = self.fields["include_collaborative_link"]
        if collaborative_enabled:
            collab_field.disabled = False
            collab_field.help_text = (
                "Required: select this or the protocol document before sending."
            )
        else:
            collab_field.initial = False
            collab_field.disabled = True
            collab_field.help_text = (
                "Enable the collaborative editor and upload the protocol document to share this link."
            )

    def clean(self):
        cleaned = super().clean()
        include_doc = cleaned.get("include_protocol_document")
        include_collab = cleaned.get("include_collaborative_link")
        if self.document_available or self.collaborative_available:
            if not include_doc and not include_collab:
                raise forms.ValidationError(
                    "Select at least one resource (protocol document or collaborative editor link) before sending."
                )
        else:
            raise forms.ValidationError(
                "Upload the protocol or enable the collaborative editor before sending."
            )
        return cleaned

    def clean_due_date(self):
        return _validate_not_same_day_date(
            self.cleaned_data.get("due_date"), "Response due date"
        )


class ActionListSendForm(forms.Form):
    due_date = forms.DateField(
        required=False,
        label="Response due date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="",
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the default invitation copy.",
    )
    include_action_list_document = forms.BooleanField(
        required=False,
        initial=False,
        label="Attach action list document",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Required: select this or the collaborative editor link before sending.",
    )
    include_collaborative_link = forms.BooleanField(
        required=False,
        initial=False,
        label="Include collaborative editor link",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        help_text="Required: select this or the action list document before sending.",
    )

    def __init__(
        self, *args, collaborative_enabled=False, document_available=False, **kwargs
    ):
        super().__init__(*args, **kwargs)
        _set_min_date_attr(self.fields["due_date"])
        self.fields["due_date"].help_text = (
            "Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today if no "
            "deadline is already set."
        )
        self.document_available = document_available
        self.collaborative_available = collaborative_enabled
        doc_field = self.fields["include_action_list_document"]
        if document_available:
            doc_field.disabled = False
            doc_field.help_text = (
                "Required: select this or the collaborative editor link before sending."
            )
        else:
            doc_field.initial = False
            doc_field.disabled = True
            doc_field.help_text = "Upload an action list document to include it here."

        collab_field = self.fields["include_collaborative_link"]
        if collaborative_enabled:
            collab_field.disabled = False
            collab_field.help_text = (
                "Required: select this or the action list document before sending."
            )
        else:
            collab_field.initial = False
            collab_field.disabled = True
            collab_field.help_text = (
                "Enable the collaborative editor and upload the action list document to share this link."
            )

    def clean(self):
        cleaned = super().clean()
        include_doc = cleaned.get("include_action_list_document")
        include_collab = cleaned.get("include_collaborative_link")
        if not (self.document_available or self.collaborative_available):
            raise forms.ValidationError(
                "Upload the action list or enable the collaborative editor before sending."
            )
        if not include_doc and not include_collab:
            raise forms.ValidationError(
                "Select at least one resource (action list document or collaborative editor link) before sending."
            )
        return cleaned

    def clean_due_date(self):
        return _validate_not_same_day_date(
            self.cleaned_data.get("due_date"), "Response due date"
        )


class ReminderScheduleForm(forms.Form):
    reminder_date = forms.DateField(
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _set_min_date_attr(self.fields["reminder_date"])
        self.fields["reminder_date"].help_text = (
            "Members without invitations will get this response deadline set. "
            f"Defaults to {_advisory_invite_response_window_days()} days from today."
        )

    def clean_reminder_date(self):
        return _validate_not_same_day_date(
            self.cleaned_data.get("reminder_date"), "Response deadline"
        )


class ProtocolReminderScheduleForm(forms.Form):
    deadline = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _set_min_datetime_attr(self.fields["deadline"])
        self.fields["deadline"].help_text = (
            "Set or update the protocol feedback deadline (date and time) for "
            "members with the protocol. Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today."
        )

    def clean_deadline(self):
        return _validate_not_same_day_datetime(
            self.cleaned_data.get("deadline"), "Protocol feedback deadline"
        )


class ActionListReminderScheduleForm(forms.Form):
    deadline = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={"type": "datetime-local", "class": "form-control"},
            format="%Y-%m-%dT%H:%M",
        ),
        input_formats=["%Y-%m-%dT%H:%M"],
        help_text="",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _set_min_datetime_attr(self.fields["deadline"])
        self.fields["deadline"].help_text = (
            "Set or update the action list feedback deadline (date and time) for "
            "members. Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today."
        )

    def clean_deadline(self):
        return _validate_not_same_day_datetime(
            self.cleaned_data.get("deadline"), "Action list feedback deadline"
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


# TODO: #15 cleanup this form, add more validation and error handling (file types supported are currently .RIS but .txt is also being used by team).
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
    search_date_start = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="Start date for the reference collection window (optional).",
    )
    search_date_end = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="End date for the reference collection window (optional).",
    )
    ris_file = forms.FileField(
        label="RIS/TXT file",
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["ris", "txt"])],
    )
    notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        help_text="Internal notes about this batch (optional).",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = self.fields["source_type"].choices
        self.fields["source_type"].choices = [
            choice for choice in choices if choice[0] != "library_link"
        ]

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("search_date_start")
        end = cleaned.get("search_date_end")
        if start and end and end < start:
            self.add_error(
                "search_date_end",
                "End date cannot be earlier than the start date.",
            )
        return cleaned


class LibraryReferenceBatchUploadForm(ReferenceBatchUploadForm):
    ris_file = forms.FileField(
        label="RIS/TXT/XML file",
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["ris", "txt", "xml"])],
    )


class ReferenceScreeningForm(forms.Form):
    reference_id = forms.IntegerField(widget=forms.HiddenInput)
    screening_status = forms.ChoiceField(
        choices=Reference.SCREENING_STATUS_CHOICES,
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    reference_folder = forms.MultipleChoiceField(
        choices=Reference.FOLDER_CHOICES,
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select form-select-sm", "size": "6"}),
        label="Reference folders",
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


class ReferenceClassificationForm(forms.Form):
    screening_status = forms.ChoiceField(
        choices=[
            ("included", "Included in this synopsis"),
            ("excluded", "Exclude from this synopsis"),
        ],
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Synopsis status",
    )
    reference_folder = forms.MultipleChoiceField(
        choices=Reference.FOLDER_CHOICES,
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "6"}),
        label="Reference folders",
    )
    screening_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Reason or notes for this synopsis-level classification",
            }
        ),
        label="Reason / notes",
        help_text="Required if you exclude the reference from this synopsis.",
    )

    def clean_screening_notes(self):
        return (self.cleaned_data.get("screening_notes") or "").strip()

    def clean(self):
        cleaned = super().clean()
        status = cleaned.get("screening_status")
        notes = cleaned.get("screening_notes") or ""
        if status == "excluded" and not notes:
            self.add_error(
                "screening_notes",
                "Provide a reason before excluding this reference from the synopsis.",
            )
        return cleaned


class LibraryReferenceUpdateForm(forms.ModelForm):
    class Meta:
        model = LibraryReference
        fields = [
            "title",
            "authors",
            "publication_year",
            "journal",
            "volume",
            "issue",
            "pages",
            "doi",
            "url",
            "language",
            "abstract",
        ]
        widgets = {
            "title": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "authors": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "publication_year": forms.NumberInput(attrs={"class": "form-control"}),
            "journal": forms.TextInput(attrs={"class": "form-control"}),
            "volume": forms.TextInput(attrs={"class": "form-control"}),
            "issue": forms.TextInput(attrs={"class": "form-control"}),
            "pages": forms.TextInput(attrs={"class": "form-control"}),
            "doi": forms.TextInput(attrs={"class": "form-control"}),
            "url": forms.URLInput(attrs={"class": "form-control"}),
            "language": forms.TextInput(attrs={"class": "form-control"}),
            "abstract": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }


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


class CollaborativeUpdateForm(forms.Form):
    document = forms.FileField(
        required=True,
        validators=[FileExtensionValidator(["docx", "pdf"])],
        widget=forms.FileInput(attrs={"class": "form-control"}),
        help_text="Upload the updated document (DOCX or PDF).",
    )
    change_reason = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Summarise the edits made during this collaborative session (optional).",
            }
        ),
        label="Change summary",
    )


class ReferenceSummaryAssignmentForm(forms.Form):
    assigned_to = forms.ModelChoiceField(
        queryset=User.objects.none(),
        required=False,
        label="Assignee",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )
    needs_help = forms.BooleanField(
        required=False,
        initial=False,
        label="Needs help",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if project:
            author_ids = project.author_users.values_list("id", flat=True)
            self.fields["assigned_to"].queryset = User.objects.filter(
                id__in=author_ids
            ).order_by("first_name", "last_name")
        else:
            self.fields["assigned_to"].queryset = User.objects.none()


class ReferenceSummaryUpdateForm(forms.ModelForm):
    action_tags = forms.MultipleChoiceField(
        required=False,
        choices=IUCN_ACTION_CHOICES,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "multiple": True}),
        label="Action (IUCN)",
    )
    threat_tags = forms.MultipleChoiceField(
        required=False,
        choices=IUCN_THREAT_CHOICES,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "multiple": True}),
        label="Threat (IUCN)",
    )
    habitat_tags = forms.MultipleChoiceField(
        required=False,
        choices=IUCN_HABITAT_CHOICES,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "multiple": True}),
        label="Habitat (IUCN)",
    )
    taxon_tags = TagCommaField(
        required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Binomial + common names, comma-separated (e.g. Anas platyrhynchos, mallard)"}
        ),
        label="Taxon tags",
    )
    location_tags = LocationListField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "One per line. Format: Place - latitude, longitude (5 decimals). Example: London, UK - 51.50740, -0.12780",
            }
        ),
        label="Location tags",
    )
    summary_author = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Name of summary author"}),
        label="Summary author",
    )
    broad_category = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Broad category"}),
        label="Broad category",
    )
    keywords = TagCommaField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Comma-separated keywords"}),
        label="Keywords",
    )
    source_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={"class": "form-control", "placeholder": "Stable URL or DOI"}),
        label="URL",
    )
    crop_type = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Crop type (if relevant)"}),
        label="Crop type",
    )
    outcomes_raw = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Outcome | Treatment value(s) | Treatment | Comparator value(s) | Comparator | Unit | Difference | Stats | p value | Notes",
            }
        ),
        label="Outcome rows",
        help_text="One outcome per line, fields separated by |",
    )
    research_design = forms.ChoiceField(
        required=False,
        choices=RESEARCH_DESIGN_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Research design",
    )
    QUALITY_SCORE_RANGES = {
        "benefits_score": (0, 100, "1"),
        "harms_score": (0, 100, "1"),
        "reliability_score": (0.0, 1.0, "0.01"),
        "relevance_score": (0.0, 1.0, "0.01"),
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        self._existing_status = instance.status if instance else None
        if "status" not in (self.data or {}):
            self.fields["status"].required = False
        if instance and instance.pk and instance.outcome_rows:
            lines = []
            for row in instance.outcome_rows:
                parts = [
                    row.get("outcome", ""),
                    row.get("treatment_value", ""),
                    row.get("treatment", ""),
                    row.get("comparator_value", ""),
                    row.get("comparator", ""),
                    row.get("unit", ""),
                    row.get("difference", ""),
                    row.get("stats", ""),
                    row.get("p_value", ""),
                    row.get("notes", ""),
                ]
                if any(part.strip() for part in parts):
                    lines.append(" | ".join(parts).strip())
            self.fields["outcomes_raw"].initial = "\n".join([line for line in lines if line.strip()])
        for field_name, (min_value, max_value, step) in self.QUALITY_SCORE_RANGES.items():
            field = self.fields.get(field_name)
            if not field:
                continue
            field.min_value = min_value
            field.max_value = max_value
            field.widget.attrs.update(
                {
                    "min": min_value,
                    "max": max_value,
                    "step": step,
                }
            )

    class Meta:
        model = ReferenceSummary
        fields = [
            "status",
            "action_description",
            "study_design",
            "sites_replications",
            "year_range",
            "habitat_and_sites",
            "region",
            "country",
            "summary_of_results",
            "action_methods",
            "experimental_design",
            "site_context_details",
            "sampling_methods_details",
            "cost_summary",
            "outcomes_raw",
            "benefits_score",
            "harms_score",
            "reliability_score",
            "relevance_score",
            "summary_author",
            "broad_category",
            "keywords",
            "source_url",
            "action_tags",
            "threat_tags",
            "taxon_tags",
            "habitat_tags",
            "location_tags",
            "crop_type",
            "research_design",
            "citation",
        ]
        widgets = {
            "status": forms.Select(attrs={"class": "form-select"}),
            "action_description": forms.TextInput(attrs={"class": "form-control"}),
            "study_design": forms.TextInput(attrs={"class": "form-control"}),
            "sites_replications": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. 5 sites, 3 replicates per treatment",
                }
            ),
            "year_range": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "e.g. 2015-2018",
                }
            ),
            "habitat_and_sites": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "region": forms.TextInput(attrs={"class": "form-control"}),
            "country": forms.TextInput(attrs={"class": "form-control"}),
            "summary_of_results": forms.Textarea(attrs={"class": "form-control", "rows": 6}),
            "action_methods": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "experimental_design": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "site_context_details": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "sampling_methods_details": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cost_summary": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Brief summary of financial costs (optional)."}
            ),
            "benefits_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "harms_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "reliability_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "relevance_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "citation": forms.TextInput(attrs={"class": "form-control"}),
        }

    def _split_tags(self, field_name):
        value = self.cleaned_data.get(field_name)
        if isinstance(value, list):
            return value
        if not value:
            return []
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return []

    def clean_action_tags(self):
        return self._split_tags("action_tags")

    def clean_threat_tags(self):
        return self._split_tags("threat_tags")

    def clean_taxon_tags(self):
        return self._split_tags("taxon_tags")

    def clean_habitat_tags(self):
        return self._split_tags("habitat_tags")

    def clean_location_tags(self):
        raw = self.cleaned_data.get("location_tags", "") or ""
        lines = [line.strip() for line in str(raw).splitlines() if line.strip()]
        coord_pattern = re.compile(r"(-?\d{1,3}\.\d{5})\s*,\s*(-?\d{1,3}\.\d{5})")
        cleaned = []
        for line in lines:
            # Guard against pathological long strings
            if len(line) > MAX_LOCATION_LINE_LENGTH:
                raise forms.ValidationError("Each location line must be reasonably short (under 200 characters).")
            match = coord_pattern.search(line.strip())
            has_numbers = bool(re.search(r"\d", line))
            if has_numbers and not match:
                raise forms.ValidationError(
                    "Coordinates must have exactly 5 decimal places for both latitude and longitude (e.g. '51.50740, -0.12780')."
                )
            if match:
                lat = float(match.group(1))
                lon = float(match.group(2))
                if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
                    raise forms.ValidationError(
                        "Coordinates must be valid latitude (-90 to 90) and longitude (-180 to 180)."
                    )
            cleaned.append(line)
        return cleaned

    def clean_keywords(self):
        return self._split_tags("keywords")

    def clean_status(self):
        value = self.cleaned_data.get("status")
        if value:
            return value
        return self._existing_status

    def clean_outcomes_raw(self):
        raw = self.cleaned_data.get("outcomes_raw", "") or ""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        parsed = []
        for line in lines:
            parts = re.split(r"(?<!\\)\|", line)
            parts = [part.replace("\\|", "|").strip() for part in parts]
            # Pad to 10 fields
            while len(parts) < 10:
                parts.append("")
            if any(parts):
                parsed.append(
                    {
                        "outcome": parts[0],
                        "treatment_value": parts[1],
                        "treatment": parts[2],
                        "comparator_value": parts[3],
                        "comparator": parts[4],
                        "unit": parts[5],
                        "difference": parts[6],
                        "stats": parts[7],
                        "p_value": parts[8],
                        "notes": parts[9],
                    }
                )
        return parsed

    def _clean_score_in_range(self, field_name):
        value = self.cleaned_data.get(field_name)
        if value in (None, ""):
            return value
        min_value, max_value, _ = self.QUALITY_SCORE_RANGES[field_name]
        if not (min_value <= value <= max_value):
            raise forms.ValidationError(f"Enter a value between {min_value} and {max_value}.")
        return value

    def clean_benefits_score(self):
        return self._clean_score_in_range("benefits_score")

    def clean_harms_score(self):
        return self._clean_score_in_range("harms_score")

    def clean_reliability_score(self):
        return self._clean_score_in_range("reliability_score")

    def clean_relevance_score(self):
        return self._clean_score_in_range("relevance_score")

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.outcome_rows = self.cleaned_data.get("outcomes_raw", [])
        for field in [
            "action_tags",
            "threat_tags",
            "taxon_tags",
            "habitat_tags",
            "location_tags",
            "keywords",
        ]:
            instance_value = self.cleaned_data.get(field, [])
            instance.__setattr__(field, instance_value if instance_value is not None else [])
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class ReferenceSummaryDraftForm(forms.ModelForm):
    def __init__(self, *args, generated_summary="", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["synopsis_draft"].required = False
        self.fields["synopsis_draft"].help_text = (
            "Saved draft text is used in compilation/export. Leave it blank to fall back to the auto-generated paragraph."
        )
        if (
            not self.is_bound
            and not (self.instance and (self.instance.synopsis_draft or "").strip())
            and (generated_summary or "").strip()
        ):
            self.initial["synopsis_draft"] = generated_summary.strip()

    class Meta:
        model = ReferenceSummary
        fields = ["synopsis_draft"]
        widgets = {
            "synopsis_draft": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 8,
                    "placeholder": "Edit the generated paragraph here, or leave blank to fall back to the auto-generated text.",
                }
            )
        }


class ReferenceActionSummaryForm(forms.ModelForm):
    class Meta:
        model = ReferenceActionSummary
        fields = ["action_name", "summary_text"]
        widgets = {
            "action_name": forms.TextInput(
                attrs={"class": "form-control", "placeholder": "Action title"}
            ),
            "summary_text": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Brief summary for this action",
                }
            ),
        }


class ReferenceSummaryCommentForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Add a comment",
            }
        ),
        label="",
    )
    parent_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        label="Attachment",
    )
    notify_assignee = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
        label="Notify assignee",
    )


class ReferenceCommentForm(forms.Form):
    body = forms.CharField(
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Add a note or comment",
            }
        ),
        label="",
    )
    parent_id = forms.IntegerField(required=False, widget=forms.HiddenInput())
    attachment = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        label="Attachment",
    )


class ReferenceDocumentForm(forms.Form):
    document = forms.FileField(
        label="Upload PDF",
        widget=forms.ClearableFileInput(attrs={"class": "form-control", "accept": "application/pdf"}),
    )
