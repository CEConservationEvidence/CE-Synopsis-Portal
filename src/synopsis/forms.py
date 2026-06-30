"""Forms and formsets for project, advisory, document, and reference workflows."""

import re

from django import forms
from django.conf import settings
from django.contrib.auth.forms import (
    AuthenticationForm,
    PasswordResetForm,
    SetPasswordForm,
)
from django.contrib.auth.models import User
from django.core.mail import EmailMultiAlternatives
from django.core.validators import FileExtensionValidator
from django.forms.models import BaseInlineFormSet, inlineformset_factory
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.text import slugify

from .tasks import queue_or_send_email_message
from .utils import (
    default_action_list_review_message,
    default_advisory_invitation_message,
    default_protocol_review_message,
    default_synopsis_review_message,
    minimum_allowed_deadline_date,
    normalize_project_action_names,
    normalize_reference_summary_citation,
    project_action_name_values,
    reference_summary_effective_citation,
    validate_inline_markup_structure,
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


def _clean_inline_markup_text(value, field_label):
    cleaned = (value or "").strip()
    try:
        validate_inline_markup_structure(cleaned)
    except ValueError as exc:
        raise forms.ValidationError(
            f"{field_label} has invalid inline formatting. {exc}"
        ) from exc
    return cleaned

from .models import (
    ActionList,
    AdvisoryBoardMember,
    AdvisoryBoardCustomField,
    CE_REFERENCE_FOLDER_CHOICES,
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
    normalize_reference_folder_values,
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
RESEARCH_DESIGN_TAG_CHOICES = [
    (value, label) for value, label in RESEARCH_DESIGN_CHOICES if value
]
MAX_RESEARCH_DESIGN_TAGS = 4

IUCN_ACTION_TAGS = [
    "Land/water protection - 1.1 Site/area protection",
    "Land/water protection - 1.2 Resource & habitat protection",
    "Land/water management - 2.1 Site/area management",
    "Land/water management - 2.2 Invasive/problematic species control",
    "Land/water management - 2.3 Habitat & natural process restoration",
    "Species management - 3.1 Species management - 3.1.1 Harvest management",
    "Species management - 3.1 Species management - 3.1.2 Trade management",
    "Species management - 3.1 Species management - 3.1.3 Limiting population growth",
    "Species management - 3.2 Species recovery",
    "Species management - 3.3 Species re-introduction - 3.3.1 Reintroduction",
    "Species management - 3.3 Species re-introduction - 3.3.1 Re-introduction",
    "Species management - 3.3 Species re-introduction - 3.3.2 Benign introduction",
    "Species management - 3.4 Ex-situ conservation - 3.4.1 Captive breeding/artificial propagation",
    "Species management - 3.4 Ex-situ conservation - 3.4.2 Genome resource bank",
    "Education & awareness - 4.1 Formal education",
    "Education & awareness - 4.2 Training",
    "Education & awareness - 4.3 Awareness & communications",
    "Law & policy - 5.1 Legislation - 5.1.1 International level",
    "Law & policy - 5.1 Legislation - 5.1.2 National level",
    "Law & policy - 5.1 Legislation - 5.1.3 Sub-national level",
    "Law & policy - 5.1 Legislation - 5.1.4 Scale unspecified",
    "Law & policy - 5.2 Policies and regulations",
    "Law & policy - 5.3 Private sector standards & codes",
    "Law & policy - 5.4 Compliance and enforcement - 5.4.1 International level",
    "Law & policy - 5.4 Compliance and enforcement - 5.4.3 Sub-national level",
    "Law & policy - 5.4 Compliance and enforcement - 5.4.4 Scale unspecified",
    "Livelihood, economic & other incentives - 6.1 Linked enterprises & livelihood alternatives",
    "Livelihood, economic & other incentives - 6.2 Substitution",
    "Livelihood, economic & other incentives - 6.3 Market forces",
    "Livelihood, economic & other incentives - 6.4 Conservation payments",
    "Livelihood, economic & other incentives - 6.5 Non-monetary values",
]

IUCN_ACTION_CHOICES = [(tag, tag) for tag in IUCN_ACTION_TAGS]
IUCN_ACTION_CHOICE_SET = set(IUCN_ACTION_TAGS)
IUCN_ACTION_TAG_ALIASES = {
    "Land/water protection-Area protection": "Land/water protection - 1.1 Site/area protection",
    "Land/water protection-Site/area stewardship": "Land/water protection - 1.2 Resource & habitat protection",
    "Land/water management-Site/area management": "Land/water management - 2.1 Site/area management",
    "Land/water management-Invasive/problematic species control": "Land/water management - 2.2 Invasive/problematic species control",
    "Land/water management-Habitat & natural process restoration": "Land/water management - 2.3 Habitat & natural process restoration",
    "Species management-Species recovery": "Species management - 3.2 Species recovery",
    "Education & awareness-Formal education": "Education & awareness - 4.1 Formal education",
    "Education & awareness-Training": "Education & awareness - 4.2 Training",
    "Education & awareness-Awareness & communications": "Education & awareness - 4.3 Awareness & communications",
    "Law & policy-Private sector standards & codes": "Law & policy - 5.3 Private sector standards & codes",
    "Law & policy-Policies & regulations": "Law & policy - 5.2 Policies and regulations",
    "Law & policy-Regulations": "Law & policy - 5.2 Policies and regulations",
    "Livelihood, economic & other incentives-Linked enterprises & livelihood alternatives": "Livelihood, economic & other incentives - 6.1 Linked enterprises & livelihood alternatives",
    "Livelihood, economic & other incentives-Market forces": "Livelihood, economic & other incentives - 6.3 Market forces",
    "Livelihood, economic & other incentives-Conservation payments": "Livelihood, economic & other incentives - 6.4 Conservation payments",
    "Livelihood, economic & other incentives-Non-monetary values": "Livelihood, economic & other incentives - 6.5 Non-monetary values",
}

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

IUCN_HABITAT_TAGS = [
    "Forest & Woodland-Boreal Woodland/Forest",
    "Forest & Woodland-Subarctic Woodland/Forest",
    "Forest & Woodland-Subantarctic Woodland/Forest",
    "Forest & Woodland-Temperate Broadleaf Woodland/Forest",
    "Forest & Woodland-Temperate Coniferous Woodland/Forest",
    "Forest & Woodland-Temperate Mixed Woodland/Forest",
    "Forest & Woodland-Subtropical/Tropical Dry Woodland/Forest",
    "Forest & Woodland-Subtropical/Tropical Moist Woodland/Lowland Forest",
    "Forest & Woodland-Subtropical/Tropical Swamp Forest",
    "Forest & Woodland-Subtropical/Tropical Moist Montane Woodland/Forest",
    "Forest & Woodland-Mangroves",
    "Forest & Woodland-Other",
    "Savanna-Dry Savanna",
    "Savanna-Moist Savanna",
    "Shrubland-Subarctic Shrubland",
    "Shrubland-Subantarctic Shrubland",
    "Shrubland-Temperate Shrubland",
    "Shrubland-Heathland",
    "Shrubland-Moorland",
    "Shrubland-Subtropical/Tropical Dry Shrubland",
    "Shrubland-Subtropical/Tropical Moist Shrubland",
    "Shrubland-Subtropical/Tropical High Altitude Shrubland",
    "Shrubland-Mediterranean-type Shrubland",
    "Shrubland-Tundra",
    "Grassland-Alpine Grasslands and Meadows",
    "Grassland-Subarctic Grassland",
    "Grassland-Subantarctic Grassland",
    "Grassland-Temperate Grassland",
    "Grassland-Subtropical/Tropical Dry Lowland Grassland",
    "Grassland-Subtropical/Tropical Seasonally Wet/Flooded Lowland Grassland",
    "Grassland-Subtropical/Tropical High Altitude Grassland",
    "Wetlands-Shrub Dominated Wetlands",
    "Wetlands-Bogs and Peatlands",
    "Wetlands-Fens",
    "Wetlands-Reedbeds",
    "Wetlands-Marshes and Swamps",
    "Wetlands-Permanent Freshwater Lakes",
    "Wetlands-Ephemeral Freshwater Lakes",
    "Wetlands-Permanent Freshwater Marshes/Pools",
    "Wetlands-Ephemeral Freshwater Marshes/Pools",
    "Wetlands-Flushes and Springs",
    "Wetlands-Geothermal Wetlands",
    "Wetlands-Saline, Brackish or Alkaline Lakes and Flats",
    "Wetlands-Permanent Saline, Brackish or Alkaline Marshes/Pools",
    "Wetlands-Ephemeral Saline, Brackish or Alkaline Marshes/Pools",
    "Wetlands-Karst and Other Subterranean Aquatic Systems",
    "Rivers, Streams, Creeks-Ephemeral Rivers, Streams, Creeks",
    "Rivers, Streams, Creeks-Permanent Rivers, Streams, Creeks",
    "Rivers, Streams, Creeks-Riparian Areas",
    "Rocky Habitats & Caves-Caves and Subterranean Habitats (dry)",
    "Rocky Habitats & Caves-Natural Exposures (cliff, scree, limestone pavement, rock outcrop)",
    "Desert-Desert",
    "Desert-Semi-desert",
    "Marine-Benthic Pebbles",
    "Marine-Benthic Rock",
    "Marine-Benthic Sand/Mud",
    "Marine-Coral Reefs",
    "Marine-Macroalgal/Kelp Beds",
    "Marine-Pelagic",
    "Marine-Reefs (other than Coral)",
    "Marine-Seagrasses",
    "Coastal-Coastal Brackish/Saline Lagoons",
    "Coastal-Coastal Caves",
    "Coastal-Coastal Sand Dunes",
    "Coastal-Coastal Shingle",
    "Coastal-Estuaries",
    "Coastal-Intertidal Mud Flats",
    "Coastal-Maritime Cliff and Slope",
    "Coastal-Rocky Shorelines",
    "Coastal-Salt Marshes",
    "Coastal-Sandy Shores/Beaches",
    "Coastal-Tidal Pools",
    "Artificial Habitats-Arable Land",
    "Artificial Habitats-Pastureland",
    "Artificial Habitats-Plantations",
    "Artificial Habitats-Gardens and Parks",
    "Artificial Habitats-Built-up Areas",
    "Artificial Habitats-Artificial Exposures (quarries, opencast mines)",
    "Artificial Habitats-Boundaries (hedges, walls, ditches)",
    "Artificial Habitats-Power Lines",
    "Artificial Habitats-Roads/Verges",
    "Artificial Habitats-Railways",
    "Artificial Habitats-Waste Tips",
    "Artificial Habitats-Dams and Reservoirs",
    "Artificial Habitats-Ponds",
    "Artificial Habitats-Aquaculture Ponds",
    "Artificial Habitats-Wastewater Treatment Areas",
    "Artificial Habitats-Canals",
    "Artificial Habitats-Drainage Channels",
    "Artificial Habitats-Marine Anthropogenic Structures",
    "Artificial Habitats-Mariculture Cages",
    "Artificial Habitats-Mari/Brackish-culture Ponds",
    "Other-Continental Ice or Glaciers",
]

IUCN_HABITAT_CHOICES = [(tag, tag) for tag in IUCN_HABITAT_TAGS]
IUCN_HABITAT_CHOICE_SET = set(IUCN_HABITAT_TAGS)
IUCN_HABITAT_TAG_ALIASES = {
    tag.split("-", 1)[1]: tag for tag in IUCN_HABITAT_TAGS
}
IUCN_HABITAT_TAG_ALIASES.update(
    {
        "Forest - Boreal": "Forest & Woodland-Boreal Woodland/Forest",
        "Forest - Subarctic": "Forest & Woodland-Subarctic Woodland/Forest",
        "Forest - Subantarctic": "Forest & Woodland-Subantarctic Woodland/Forest",
        "Forest - Subtropical/Tropical Dry": "Forest & Woodland-Subtropical/Tropical Dry Woodland/Forest",
        "Forest - Subtropical/Tropical Moist Lowland": "Forest & Woodland-Subtropical/Tropical Moist Woodland/Lowland Forest",
        "Forest - Subtropical/Tropical Swamp": "Forest & Woodland-Subtropical/Tropical Swamp Forest",
        "Forest - Subtropical/Tropical Moist Montane": "Forest & Woodland-Subtropical/Tropical Moist Montane Woodland/Forest",
        "Forest - Subtropical/Tropical Mangrove Vegetation Above High Tide Level": "Forest & Woodland-Mangroves",
        "Wetlands (inland) - Shrub Dominated Wetlands": "Wetlands-Shrub Dominated Wetlands",
        "Wetlands (inland) - Bogs, Marshes, Swamps, Fens, Peatlands": "Wetlands-Bogs and Peatlands",
        "Wetlands (inland) - Permanent Freshwater Lakes": "Wetlands-Permanent Freshwater Lakes",
        "Wetlands (inland) - Seasonal/Intermittent Freshwater Lakes (over 8ha)": "Wetlands-Ephemeral Freshwater Lakes",
        "Wetlands (inland) - Permanent Freshwater Marshes/Pools (under 8ha)": "Wetlands-Permanent Freshwater Marshes/Pools",
        "Wetlands (inland) - Seasonal/Intermittent Freshwater Marshes/Pools (under 8ha)": "Wetlands-Ephemeral Freshwater Marshes/Pools",
        "Wetlands (inland) - Freshwater Springs and Oases": "Wetlands-Flushes and Springs",
        "Wetlands (inland) - Geothermal Wetlands": "Wetlands-Geothermal Wetlands",
        "Wetlands (inland) - Permanent Saline, Brackish or Alkaline Lakes": "Wetlands-Saline, Brackish or Alkaline Lakes and Flats",
        "Wetlands (inland) - Seasonal/Intermittent Saline, Brackish or Alkaline Lakes and Flats": "Wetlands-Saline, Brackish or Alkaline Lakes and Flats",
        "Wetlands (inland) - Permanent Saline, Brackish or Alkaline Marshes/Pools": "Wetlands-Permanent Saline, Brackish or Alkaline Marshes/Pools",
        "Wetlands (inland) - Seasonal/Intermittent Saline, Brackish or Alkaline Marshes/Pools": "Wetlands-Ephemeral Saline, Brackish or Alkaline Marshes/Pools",
        "Wetlands (inland) - Karst and Other Subterranean Hydrological Systems": "Wetlands-Karst and Other Subterranean Aquatic Systems",
        "Wetlands (inland) - Permanent Rivers/Streams/Creeks": "Rivers, Streams, Creeks-Permanent Rivers, Streams, Creeks",
        "Wetlands (inland) - Seasonal/Intermittent/Irregular Rivers/Streams/Creeks": "Rivers, Streams, Creeks-Ephemeral Rivers, Streams, Creeks",
        "Rocky Areas - Inland Cliffs, Rock Outcrops and Caves": "Rocky Habitats & Caves-Natural Exposures (cliff, scree, limestone pavement, rock outcrop)",
        "Caves and Subterranean Habitats (non-aquatic)": "Rocky Habitats & Caves-Caves and Subterranean Habitats (dry)",
        "Marine Coral Reefs": "Marine-Coral Reefs",
        "Marine Seagrass (submerged)": "Marine-Seagrasses",
        "Marine Pelagic": "Marine-Pelagic",
        "Marine Estuarine": "Coastal-Estuaries",
        "Marine Coastal Lagoon": "Coastal-Coastal Brackish/Saline Lagoons",
        "Marine Rocky Shores": "Coastal-Rocky Shorelines",
        "Marine Salt Marshes": "Coastal-Salt Marshes",
        "Marine Tidepools": "Coastal-Tidal Pools",
        "Artificial - Arable Land": "Artificial Habitats-Arable Land",
        "Artificial - Pastureland": "Artificial Habitats-Pastureland",
        "Artificial - Plantations": "Artificial Habitats-Plantations",
        "Artificial - Rural Gardens": "Artificial Habitats-Gardens and Parks",
        "Artificial - Urban Areas": "Artificial Habitats-Built-up Areas",
        "Artificial - Aquatic - Ponds": "Artificial Habitats-Ponds",
        "Artificial - Aquatic - Aquaculture Ponds": "Artificial Habitats-Aquaculture Ponds",
        "Artificial - Aquatic - Dams and Reservoirs": "Artificial Habitats-Dams and Reservoirs",
        "Artificial - Aquatic - Wastewater Treatment Areas": "Artificial Habitats-Wastewater Treatment Areas",
        "Artificial - Aquatic - Excavations": "Artificial Habitats-Artificial Exposures (quarries, opencast mines)",
        "Bogs and Peatlands (general/unspecified)": "Wetlands-Bogs and Peatlands",
        "Swamps": "Wetlands-Marshes and Swamps",
        "Marshes and Swamps": "Wetlands-Marshes and Swamps",
    }
)


def _normalize_habitat_tag(tag):
    cleaned = (tag or "").strip()
    if not cleaned:
        return ""
    return IUCN_HABITAT_TAG_ALIASES.get(cleaned, cleaned)


def _normalize_action_tag(tag):
    cleaned = (tag or "").strip()
    if not cleaned:
        return ""
    return IUCN_ACTION_TAG_ALIASES.get(cleaned, cleaned)


def _tag_values(tags):
    if not tags:
        return []
    if isinstance(tags, str):
        return [part.strip() for part in tags.split(",") if part.strip()]
    return list(tags)


def normalize_action_tags(tags):
    normalized = []
    seen = set()
    for tag in _tag_values(tags):
        cleaned = _normalize_action_tag(tag)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


def normalize_habitat_tags(tags):
    normalized = []
    seen = set()
    for tag in _tag_values(tags):
        cleaned = _normalize_habitat_tag(tag)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        normalized.append(cleaned)
    return normalized


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
        "External Author",
    ),
    ("manager", "Manager"),
]
class ProtocolUpdateForm(forms.ModelForm):
    document = forms.FileField(
        required=False,
        validators=[FileExtensionValidator(["pdf", "docx"])],
        widget=forms.FileInput(
            attrs={"class": "form-control", "data-reset-before-select": "true"}
        ),
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
        widget=forms.FileInput(
            attrs={"class": "form-control", "data-reset-before-select": "true"}
        ),
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
    global_role = forms.ChoiceField(
        choices=GLOBAL_ROLE_CHOICES, help_text="Global role (not tied to a project)"
    )
    assigned_projects = forms.ModelMultipleChoiceField(
        queryset=Project.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "form-check-input"}
        ),
        label="Assigned synopses",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "given-name"}
        )
        self.fields["last_name"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "family-name"}
        )
        self.fields["email"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "email"}
        )
        self.fields["global_role"].widget.attrs.update({"class": "form-select"})
        self.fields["email"].help_text = (
            "This will be the login email and username."
        )
        self.fields["global_role"].help_text = (
            "Managers can access the manager dashboard. Authors use project-level roles."
        )
        self.fields["assigned_projects"].queryset = Project.objects.order_by("title")
        self.fields["assigned_projects"].label_from_instance = (
            lambda project: project.title
        )
        self.fields["assigned_projects"].help_text = (
            "Optional. For external authors, these are the only synopses they can see on their home page and open directly."
        )

    def clean_email(self):
        return self.cleaned_data["email"].strip().lower()


class ManagerUserUpdateForm(forms.Form):
    first_name = forms.CharField(max_length=150)
    last_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(help_text="This will be the login email and username.")
    global_role = forms.ChoiceField(choices=GLOBAL_ROLE_CHOICES)
    is_active = forms.BooleanField(required=False, label="Account is active")
    assigned_projects = forms.ModelMultipleChoiceField(
        queryset=Project.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(
            attrs={"class": "form-check-input"}
        ),
        label="Assigned synopses",
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["first_name"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "given-name"}
        )
        self.fields["last_name"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "family-name"}
        )
        self.fields["email"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "email"}
        )
        self.fields["global_role"].widget.attrs.update({"class": "form-select"})
        self.fields["is_active"].widget.attrs.update({"class": "form-check-input"})
        self.fields["global_role"].help_text = (
            "This controls the user’s global portal access level."
        )
        self.fields["assigned_projects"].queryset = Project.objects.order_by("title")
        self.fields["assigned_projects"].label_from_instance = (
            lambda project: project.title
        )
        self.fields["assigned_projects"].help_text = (
            "These synopses are assigned to this user as an author. For external authors, only these synopses appear on the dashboard and can be opened."
        )
        if self.user is not None and not self.is_bound:
            self.initial["assigned_projects"] = UserRole.objects.filter(
                user=self.user, role="author"
            ).values_list("project_id", flat=True)

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if not email:
            return email
        qs = User.objects.filter(email__iexact=email) | User.objects.filter(
            username__iexact=email
        )
        if self.user is not None:
            qs = qs.exclude(pk=self.user.pk)
        if qs.exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email


class ManagerUserDeleteForm(forms.Form):
    confirm_email = forms.EmailField(
        label="Type the account email to confirm deletion"
    )

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.fields["confirm_email"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "off"}
        )

    def clean_confirm_email(self):
        value = self.cleaned_data["confirm_email"].strip().lower()
        if self.user is None:
            return value
        expected = (self.user.email or self.user.username or "").strip().lower()
        if value != expected:
            raise forms.ValidationError("Enter the exact account email to confirm deletion.")
        return value


class PortalAuthenticationForm(AuthenticationForm):
    username = forms.CharField(
        label="Email or username",
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "autocomplete": "username",
                "autofocus": True,
            }
        ),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(
            attrs={"class": "form-control", "autocomplete": "current-password"}
        ),
    )
    remember_me = forms.BooleanField(
        required=False,
        initial=False,
        label="Keep me signed in on this device",
    )

    error_messages = {
        "invalid_login": "Enter a correct email and password.",
        "inactive": "This account is inactive.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request=request, *args, **kwargs)
        self.fields["remember_me"].widget.attrs.update({"class": "form-check-input"})

    def clean_username(self):
        value = (self.cleaned_data.get("username") or "").strip()
        return value.lower() if "@" in value else value


class PortalPasswordResetForm(PasswordResetForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["email"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "email"}
        )

    def send_mail(
        self,
        subject_template_name,
        email_template_name,
        context,
        from_email,
        to_email,
        html_email_template_name=None,
    ):
        subject = render_to_string(subject_template_name, context)
        subject = "".join(subject.splitlines()).strip()
        body = render_to_string(email_template_name, context)
        message = EmailMultiAlternatives(
            subject=subject,
            body=body,
            from_email=from_email,
            to=[to_email],
        )
        if html_email_template_name:
            html_email = render_to_string(html_email_template_name, context)
            message.attach_alternative(html_email, "text/html")
        queue_or_send_email_message(message)


class PortalSetPasswordForm(SetPasswordForm):
    error_messages = {
        **SetPasswordForm.error_messages,
        "password_mismatch": "The two password fields did not match.",
    }

    def __init__(self, user, *args, **kwargs):
        super().__init__(user, *args, **kwargs)
        self.fields["new_password1"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "new-password"}
        )
        self.fields["new_password2"].widget.attrs.update(
            {"class": "form-control", "autocomplete": "new-password"}
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
        help_text="Included after the standard message.",
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
        self.fields["display_group"].choices = (
            AdvisoryBoardCustomField.DISPLAY_GROUP_CHOICES
        )

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


class SynopsisTitleForm(forms.Form):
    title = forms.CharField(
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control", "placeholder": "Title"}
        ),
        label="Title",
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
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Intervention / action name",
                "list": "project-action-name-suggestions",
            }
        ),
        label="Intervention",
    )
    iucn_actions = forms.ModelMultipleChoiceField(
        queryset=IUCNCategory.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": 5}),
        label="IUCN actions",
    )

    def __init__(self, *args, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["iucn_actions"].queryset = IUCNCategory.objects.filter(
            kind=IUCNCategory.KIND_ACTION,
            is_active=True,
        ).order_by("position", "name")
        self.fields["iucn_actions"].label_from_instance = lambda obj: obj.name

    def clean_title(self):
        return (self.cleaned_data.get("title") or "").strip()


class SynopsisBackgroundForm(forms.Form):
    background_text = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "data-inline-markup": "true",
                "placeholder": "Brief background (<200 words): description, context, related literature/harms.",
            }
        ),
        label="Background",
        help_text=(
            "Formatting supported: italics, subscript, superscript, and inserted symbols. "
            "This formatting is preserved in the portal and DOCX export."
        ),
    )
    background_references = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Background references (one per line, optional contextual sources; not limited by the search end date).",
            }
        ),
        label="Background references",
        help_text="Optional. Use any relevant contextual references here. They do not need to be published before the search end date.",
    )

    def clean_background_text(self):
        return _clean_inline_markup_text(
            self.cleaned_data.get("background_text"),
            "Background",
        )


class ProjectActionNameBankForm(forms.Form):
    action_names_text = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 8,
                "placeholder": "Enter one action name per line",
            }
        ),
        label="Saved action names",
        help_text=(
            "Enter one action name per line. These names appear in the summary action dropdown "
            "and as suggestions when creating or renaming synopsis interventions."
        ),
    )

    def clean_action_names_text(self):
        names = normalize_project_action_names(
            self.cleaned_data.get("action_names_text", "")
        )
        return "\n".join(names)


class SynopsisInterventionDetailsForm(forms.Form):
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
                "data-inline-markup": "true",
                "placeholder": "Key message statement.",
            }
        ),
        label="Statement",
        help_text=(
            "Formatting supported: italics, subscript, superscript, and inserted symbols. "
            "This formatting is preserved in the portal and DOCX export."
        ),
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
        return _clean_inline_markup_text(
            self.cleaned_data.get("statement"),
            "Statement",
        )


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
        fields = [
            "title",
            "description",
            "protocol_relevant",
            "advisory_board_relevant",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control"}),
            "description": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Optional short description of the synopsis",
                }
            ),
            "protocol_relevant": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
            "advisory_board_relevant": forms.CheckboxInput(
                attrs={"class": "form-check-input"}
            ),
        }
        error_messages = {
            "title": {
                "required": "Enter a title for the synopsis.",
            }
        }
        labels = {
            "description": "Description (optional)",
            "protocol_relevant": "Protocol is relevant for this project",
            "advisory_board_relevant": "Advisory board is relevant for this project",
        }
        help_texts = {
            "protocol_relevant": "Untick this if this synopsis will not use a protocol in the portal.",
            "advisory_board_relevant": "Untick this if this synopsis will not use an advisory board in the portal.",
        }

    def clean_title(self):
        title = self.cleaned_data.get("title", "").strip()
        if not title:
            raise forms.ValidationError("Enter a title for the synopsis.")
        return title

    def clean_description(self):
        return self.cleaned_data.get("description", "").strip()


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
        help_text="Included after the standard message.",
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
    standard_message = forms.CharField(
        required=False,
        label="Standard message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 5}
        ),
        help_text=(
            "The main review request included in the email. You can edit it "
            "before sending."
        ),
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the standard message.",
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
        if not self.is_bound:
            self.fields["standard_message"].initial = (
                default_protocol_review_message()
            )
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
    standard_message = forms.CharField(
        required=False,
        label="Standard message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 5}
        ),
        help_text=(
            "The main review request included in the email. You can edit it "
            "before sending."
        ),
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the standard message.",
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
        if not self.is_bound:
            self.fields["standard_message"].initial = (
                default_action_list_review_message()
            )
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


class SynopsisSendForm(forms.Form):
    due_date = forms.DateField(
        required=False,
        label="Response due date",
        widget=forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        help_text="",
    )
    standard_message = forms.CharField(
        required=False,
        label="Standard message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 5}
        ),
        help_text=(
            "The main review request included in the email. You can edit it "
            "before sending."
        ),
    )
    message = forms.CharField(
        required=False,
        label="Additional message",
        widget=forms.Textarea(
            attrs={"class": "form-control", "rows": 4, "placeholder": "Optional personal note"}
        ),
        help_text="Included after the standard message.",
    )
    synopsis_document = forms.FileField(
        required=False,
        label="Synopsis document",
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["doc", "docx", "pdf"])],
        help_text=(
            "Optional. Attach this file instead of the generated synopsis export. "
            "Accepted formats: .doc, .docx, .pdf."
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _set_min_date_attr(self.fields["due_date"])
        if not self.is_bound:
            self.fields["standard_message"].initial = (
                default_synopsis_review_message()
            )
        self.fields["due_date"].help_text = (
            "Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today if no "
            "deadline is already set."
        )

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
            "already-sent accepted members. Updating it changes the saved deadline "
            "for all of them at once, but does not send a new email immediately. Defaults to "
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
            "already-sent accepted members. Updating it changes the saved deadline "
            "for all of them at once, but does not send a new email immediately. Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today."
        )

    def clean_deadline(self):
        return _validate_not_same_day_datetime(
            self.cleaned_data.get("deadline"), "Action list feedback deadline"
        )


class SynopsisReminderScheduleForm(forms.Form):
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
            "Set or update the synopsis feedback deadline (date and time) for "
            "members who have been sent the synopsis. Defaults to "
            f"{_advisory_document_feedback_window_days()} days from today."
        )

    def clean_deadline(self):
        return _validate_not_same_day_datetime(
            self.cleaned_data.get("deadline"), "Synopsis feedback deadline"
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


class SynopsisFeedbackForm(forms.Form):
    content = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 6,
                "placeholder": "Share your comments on the synopsis here",
            }
        ),
    )
    uploaded_document = forms.FileField(
        required=False,
        widget=forms.ClearableFileInput(attrs={"class": "form-control"}),
        validators=[FileExtensionValidator(["doc", "docx", "pdf"])],
        help_text="Upload your annotated synopsis document (optional). Accepted formats: .doc, .docx, .pdf.",
    )


class ProtocolFeedbackCloseForm(forms.Form):
    message = forms.CharField(
        required=False,
        label="Closure note for advisory board",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Optional note shown after the protocol feedback window has been closed.",
            }
        ),
        help_text=(
            "Shown only when advisory board members open an existing protocol feedback link after closure. "
            "This is not sent as a reminder or deadline-change email."
        ),
    )


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
        label="Shared CE subject categories",
        help_text=(
            "For library-linked references, changing these categories updates the shared library record and is reflected in linked synopsis copies."
        ),
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

    def clean_reference_folder(self):
        return normalize_reference_folder_values(
            self.cleaned_data.get("reference_folder") or []
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
        label="Shared CE subject categories",
        help_text=(
            "This is a reference-level setting. For library-linked references, changing these categories updates the shared library record and is reflected in linked synopsis copies."
        ),
    )
    screening_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 3,
                "placeholder": "Reason or notes for this reference classification",
            }
        ),
        label="Reason / notes",
        help_text="Required if you exclude the reference from this synopsis.",
    )

    def clean_screening_notes(self):
        return (self.cleaned_data.get("screening_notes") or "").strip()

    def clean_reference_folder(self):
        return normalize_reference_folder_values(
            self.cleaned_data.get("reference_folder") or []
        )

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
    reference_folder = forms.MultipleChoiceField(
        choices=CE_REFERENCE_FOLDER_CHOICES,
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select", "size": "8"}),
        label="Shared CE subject categories",
        help_text=(
            "These shared categories apply across the CE reference database and are reused when the reference is linked into synopses."
        ),
    )

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
            "reference_folder",
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

    def clean_reference_folder(self):
        return normalize_reference_folder_values(
            self.cleaned_data.get("reference_folder") or []
        )


class ActionListFeedbackCloseForm(forms.Form):
    message = forms.CharField(
        required=False,
        label="Closure note for advisory board",
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "Optional note shown after the action list feedback window has been closed.",
            }
        ),
        help_text=(
            "Shown only when advisory board members open an existing action list feedback link after closure. "
            "This is not sent as a reminder or deadline-change email."
        ),
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
    ACTION_CUSTOM_VALUE = "__custom__"

    action_choice = forms.ChoiceField(
        required=False,
        widget=forms.Select(attrs={"class": "form-select"}),
        label="Action",
    )
    action_custom = forms.CharField(
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "form-control",
                "placeholder": "Enter an action if it is not in the project action list yet",
            }
        ),
        label="Custom action",
    )
    action_tags = forms.MultipleChoiceField(
        required=False,
        choices=IUCN_ACTION_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "tag-choice-input"}),
        label="Action (IUCN)",
    )
    threat_tags = forms.MultipleChoiceField(
        required=False,
        choices=IUCN_THREAT_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "tag-choice-input"}),
        label="Threat (IUCN)",
    )
    habitat_tags = forms.MultipleChoiceField(
        required=False,
        choices=IUCN_HABITAT_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "tag-choice-input"}),
        label="Habitat (Conservation Evidence)",
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
                "placeholder": "Use one free-text result sentence per line, or a structured line like: Outcome | Treatment value(s) | Treatment | Comparator value(s) | Comparator | Unit | Difference | Stats | p value | Notes",
            }
        ),
        label="Outcome notes",
        help_text="Optional. Use either one free-text result sentence per line, or a structured line with | separators for numeric comparisons.",
    )
    methods_and_design = forms.CharField(
        required=False,
        widget=forms.Textarea(
            attrs={
                "class": "form-control",
                "rows": 5,
                "placeholder": "Describe any methods, design, sampling or context notes you want to keep together.",
            }
        ),
        label="Methods, design and context notes",
        help_text="Optional. Use one flexible box for any methods, design, sampling or context details that help you write the summary.",
    )
    research_design = forms.MultipleChoiceField(
        required=False,
        choices=RESEARCH_DESIGN_TAG_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={"class": "tag-choice-input"}),
        label="Research design tags",
    )
    QUALITY_SCORE_RANGES = {
        "benefits_score": (0, 100, "1"),
        "harms_score": (0, 100, "1"),
        "reliability_score": (0.0, 1.0, "0.01"),
        "relevance_score": (0.0, 1.0, "0.01"),
    }

    def __init__(self, *args, project, **kwargs):
        super().__init__(*args, **kwargs)
        instance = getattr(self, "instance", None)
        self.fields["study_design"].required = False
        self.fields["study_design"].help_text = (
            "Optional. Used in the first sentence of the summary paragraph. "
            "If you leave it blank, the system will build it from the CE research design tags below."
        )
        action_choices = [("", "Select an action")]
        if project is not None:
            for label in project_action_name_values(
                project, include_intervention_titles=True
            ):
                action_choices.append((label, label))
        action_choices.append((self.ACTION_CUSTOM_VALUE, "Other / enter custom action"))
        self.fields["action_choice"].choices = action_choices
        self._existing_status = instance.status if instance else None
        if instance and instance.pk:
            action_tag_choices = list(self.fields["action_tags"].choices)
            current_action_tags = list(instance.action_tags or [])
            legacy_action_tags = []
            normalized_action_tags = normalize_action_tags(current_action_tags)
            for tag in current_action_tags:
                normalized = _normalize_action_tag(tag)
                if (
                    normalized not in IUCN_ACTION_CHOICE_SET
                    and tag not in IUCN_ACTION_CHOICE_SET
                ):
                    legacy_action_tags.append(tag)
            if legacy_action_tags:
                for tag in legacy_action_tags:
                    if tag not in {value for value, _label in action_tag_choices}:
                        action_tag_choices.append((tag, f"{tag} (legacy saved value)"))
                self.fields["action_tags"].choices = action_tag_choices
            if not self.is_bound and normalized_action_tags:
                self.initial["action_tags"] = normalized_action_tags

            habitat_choices = list(self.fields["habitat_tags"].choices)
            current_habitat_tags = list(instance.habitat_tags or [])
            legacy_habitat_tags = []
            normalized_habitat_tags = normalize_habitat_tags(current_habitat_tags)
            for tag in current_habitat_tags:
                normalized = _normalize_habitat_tag(tag)
                if normalized not in IUCN_HABITAT_CHOICE_SET and tag not in IUCN_HABITAT_CHOICE_SET:
                    legacy_habitat_tags.append(tag)
            if legacy_habitat_tags:
                for tag in legacy_habitat_tags:
                    if tag not in {value for value, _label in habitat_choices}:
                        habitat_choices.append((tag, f"{tag} (legacy saved value)"))
                self.fields["habitat_tags"].choices = habitat_choices
            if not self.is_bound and normalized_habitat_tags:
                self.initial["habitat_tags"] = normalized_habitat_tags
        if not self.is_bound and instance and instance.research_design:
            self.initial["research_design"] = self._split_research_design_value(
                instance.research_design
            )
        if "status" not in (self.data or {}):
            self.fields["status"].required = False
        if instance and instance.pk and instance.outcome_rows:
            lines = []
            for row in instance.outcome_rows:
                sentence = (row.get("sentence", "") or "").strip()
                if sentence:
                    lines.append(sentence)
                    continue
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
        if not self.is_bound and instance:
            current_action = (instance.action_description or "").strip()
            available_values = {value for value, _label in action_choices}
            if current_action:
                if current_action in available_values:
                    self.initial["action_choice"] = current_action
                else:
                    self.initial["action_choice"] = self.ACTION_CUSTOM_VALUE
                    self.initial["action_custom"] = current_action
            methods_parts = [
                (instance.action_methods or "").strip(),
                (instance.experimental_design or "").strip(),
            ]
            self.fields["methods_and_design"].initial = "\n\n".join(
                [part for part in methods_parts if part]
            )
            self.initial["citation"] = reference_summary_effective_citation(instance)
        self.fields["citation"].help_text = (
            "This starts from the shared reference database citation. "
            "Editing it here changes only this summary/synopsis export and does not update the shared reference database. "
            "Use <i>...</i> or <em>...</em> for italics."
        )
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
            "study_design",
            "sites_replications",
            "year_range",
            "habitat_and_sites",
            "region",
            "country",
            "summary_of_results",
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
            "site_context_details": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "sampling_methods_details": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cost_summary": forms.Textarea(
                attrs={"class": "form-control", "rows": 2, "placeholder": "Brief summary of financial costs (optional)."}
            ),
            "benefits_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "harms_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "reliability_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "relevance_score": forms.NumberInput(attrs={"class": "form-control", "step": "any"}),
            "citation": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 3,
                    "placeholder": "Leave this matching the shared reference citation, or enter a synopsis-only override. Use <i>...</i> for italics.",
                }
            ),
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

    def _clean_structured_markup_field(self, field_name, field_label):
        return _clean_inline_markup_text(
            self.cleaned_data.get(field_name),
            field_label,
        )

    def clean_study_design(self):
        return self._clean_structured_markup_field("study_design", "Study design")

    def clean_sites_replications(self):
        return self._clean_structured_markup_field(
            "sites_replications",
            "Sites / replications",
        )

    def clean_year_range(self):
        return self._clean_structured_markup_field("year_range", "Year range")

    def clean_habitat_and_sites(self):
        return self._clean_structured_markup_field(
            "habitat_and_sites",
            "Habitat and sites",
        )

    def clean_region(self):
        return self._clean_structured_markup_field("region", "Region")

    def clean_country(self):
        return self._clean_structured_markup_field("country", "Country")

    def clean_summary_of_results(self):
        return self._clean_structured_markup_field(
            "summary_of_results",
            "Summary of results",
        )

    def clean_site_context_details(self):
        return self._clean_structured_markup_field(
            "site_context_details",
            "Site context details",
        )

    def clean_sampling_methods_details(self):
        return self._clean_structured_markup_field(
            "sampling_methods_details",
            "Sampling methods details",
        )

    def clean_methods_and_design(self):
        return self._clean_structured_markup_field(
            "methods_and_design",
            "Methods, design and context notes",
        )

    def clean_action_tags(self):
        return normalize_action_tags(self._split_tags("action_tags"))

    def clean_threat_tags(self):
        return self._split_tags("threat_tags")

    def clean_taxon_tags(self):
        return self._split_tags("taxon_tags")

    def clean_habitat_tags(self):
        return normalize_habitat_tags(self._split_tags("habitat_tags"))

    @staticmethod
    def _split_research_design_value(value):
        if isinstance(value, (list, tuple)):
            return [str(part).strip() for part in value if str(part).strip()]
        if not value:
            return []
        return [part.strip() for part in re.split(r";|,", str(value)) if part.strip()]

    def clean_research_design(self):
        values = self.cleaned_data.get("research_design") or []
        if len(values) > MAX_RESEARCH_DESIGN_TAGS:
            raise forms.ValidationError(
                f"Select up to {MAX_RESEARCH_DESIGN_TAGS} research design tags."
            )
        return "; ".join(values)

    @staticmethod
    def _build_study_design_from_research_design(value):
        tags = ReferenceSummaryUpdateForm._split_research_design_value(value)
        normalized = [
            str(tag).replace("*", "").strip().lower()
            for tag in tags
            if str(tag).replace("*", "").strip()
        ]
        if not normalized:
            return ""
        if len(normalized) == 1:
            label = normalized[0]
            if label.endswith("study") or label.endswith("review"):
                return label
            return f"{label} study"
        phrase = ", ".join(normalized)
        if not (phrase.endswith("study") or phrase.endswith("review")):
            phrase = f"{phrase} study"
        return phrase

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

    def clean_action_custom(self):
        return (self.cleaned_data.get("action_custom") or "").strip()

    def clean_outcomes_raw(self):
        raw = self.cleaned_data.get("outcomes_raw", "") or ""
        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        parsed = []
        for line in lines:
            if not re.search(r"(?<!\\)\|", line):
                parsed.append({"sentence": line.replace("\\|", "|")})
                continue
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
        try:
            for row in parsed:
                for value in row.values():
                    validate_inline_markup_structure(value or "")
        except ValueError as exc:
            raise forms.ValidationError(
                f"Outcome notes has invalid inline formatting. {exc}"
            ) from exc
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

    def clean(self):
        cleaned = super().clean()
        action_choice = (cleaned.get("action_choice") or "").strip()
        action_custom = (cleaned.get("action_custom") or "").strip()
        if action_choice == self.ACTION_CUSTOM_VALUE:
            if not action_custom:
                self.add_error(
                    "action_custom",
                    "Enter the action name if you choose a custom action.",
                )
            cleaned["action_description"] = action_custom
        elif action_choice:
            cleaned["action_description"] = action_choice
        else:
            cleaned["action_description"] = action_custom
        study_design = (cleaned.get("study_design") or "").strip()
        if study_design:
            cleaned["study_design"] = study_design
        else:
            cleaned["study_design"] = self._build_study_design_from_research_design(
                cleaned.get("research_design")
            )
        cleaned["citation"] = normalize_reference_summary_citation(
            cleaned.get("citation"),
            self.instance.reference if self.instance and self.instance.reference_id else None,
        )
        return cleaned

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.action_description = (
            self.cleaned_data.get("action_description", "").strip()
        )
        combined_methods = (self.cleaned_data.get("methods_and_design") or "").strip()
        instance.action_methods = combined_methods
        instance.experimental_design = ""
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
        instance.citation = self.cleaned_data.get("citation", "")
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class ReferenceSummaryDraftForm(forms.ModelForm):
    def __init__(self, *args, generated_summary="", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["synopsis_draft"].required = False
        self.fields["synopsis_draft"].help_text = (
            "Saving here tells the system to use this paragraph for compilation and export. "
            "Switch back to the auto-generated paragraph if you want changes in the structured fields above to flow through again. "
            "Formatting supported: <i>...</i> or <em>...</em> for italics, <sub>...</sub> for subscript, "
            "and <sup>...</sup> for superscript. Pasted symbols are preserved."
        )
        if (
            not self.is_bound
            and self.instance
        ):
            saved_draft = (self.instance.synopsis_draft or "").strip()
            generated_summary = (generated_summary or "").strip()
            if self.instance.use_custom_synopsis_draft and saved_draft:
                self.initial["synopsis_draft"] = saved_draft
            elif generated_summary:
                self.initial["synopsis_draft"] = generated_summary
            else:
                self.initial["synopsis_draft"] = saved_draft

    class Meta:
        model = ReferenceSummary
        fields = ["synopsis_draft"]
        widgets = {
            "synopsis_draft": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 8,
                    "data-inline-markup": "true",
                    "placeholder": "Edit the generated paragraph here, or leave blank to fall back to the auto-generated text.",
                }
            )
        }

    def clean_synopsis_draft(self):
        return _clean_inline_markup_text(
            self.cleaned_data.get("synopsis_draft"),
            "Summary paragraph",
        )


class ReferenceSummaryParagraphNotesForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paragraph_notes"].required = False
        self.fields["paragraph_notes"].help_text = (
            "Internal notes for this paragraph only. Use this to explain wording, numbers, study design calls, or anything future authors should remember. These notes stay in the portal and are not exported in the synopsis."
        )

    class Meta:
        model = ReferenceSummary
        fields = ["paragraph_notes"]
        widgets = {
            "paragraph_notes": forms.Textarea(
                attrs={
                    "class": "form-control",
                    "rows": 4,
                    "placeholder": "Example: Yes, this is 10 species not 11; see Fig. 4. Or: not replicated because only one treatment site was sampled.",
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
