from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


FOLDER_CHOICES = [
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
FOLDER_ORDER = {value: index for index, (value, _label) in enumerate(FOLDER_CHOICES)}
FOLDER_SET = {value for value, _label in FOLDER_CHOICES}


def _normalize(values):
    if not values:
        return []
    cleaned = []
    seen = set()
    for value in values:
        if not value or value not in FOLDER_SET or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    cleaned.sort(key=lambda value: FOLDER_ORDER.get(value, 10_000))
    return cleaned


def backfill_library_reference_folders(apps, schema_editor):
    LibraryReference = apps.get_model("synopsis", "LibraryReference")
    Reference = apps.get_model("synopsis", "Reference")

    for library_reference in LibraryReference.objects.all().iterator():
        related_references = list(
            Reference.objects.filter(library_reference_id=library_reference.id).only(
                "id", "reference_folder"
            )
        )
        combined = []
        for project_reference in related_references:
            combined.extend(project_reference.reference_folder or [])
        normalized = _normalize(combined)
        if _normalize(library_reference.reference_folder or []) != normalized:
            library_reference.reference_folder = normalized
            library_reference.save(update_fields=["reference_folder"])
        for project_reference in related_references:
            if _normalize(project_reference.reference_folder or []) != normalized:
                project_reference.reference_folder = normalized
                project_reference.save(update_fields=["reference_folder"])


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0095_referencesummary_exclusion_reason_and_status"),
    ]

    operations = [
        migrations.AddField(
            model_name="libraryreference",
            name="reference_folder",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="Shared CE subject folders assigned to this reference across the library.",
            ),
        ),
        migrations.CreateModel(
            name="LibraryReferenceFolderHistory",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("previous_folders", models.JSONField(blank=True, default=list)),
                ("new_folders", models.JSONField(blank=True, default=list)),
                ("change_source", models.CharField(blank=True, max_length=50)),
                (
                    "created_at",
                    models.DateTimeField(
                        default=django.utils.timezone.now, editable=False
                    ),
                ),
                (
                    "changed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="library_reference_folder_changes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "library_reference",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="folder_history",
                        to="synopsis.libraryreference",
                    ),
                ),
                (
                    "source_project",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="library_reference_folder_changes",
                        to="synopsis.project",
                    ),
                ),
                (
                    "source_reference",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="library_folder_history_entries",
                        to="synopsis.reference",
                    ),
                ),
            ],
            options={"ordering": ["-created_at", "-id"]},
        ),
        migrations.RunPython(
            backfill_library_reference_folders, migrations.RunPython.noop
        ),
    ]
