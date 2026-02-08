from django.conf import settings
from django.db import migrations, models
import django.core.validators
import django.db.models.deletion


def forwards_link_library_references(apps, schema_editor):
    Reference = apps.get_model("synopsis", "Reference")
    LibraryReference = apps.get_model("synopsis", "LibraryReference")
    db_alias = schema_editor.connection.alias

    for ref in Reference.objects.using(db_alias).order_by("id").iterator():
        lib = (
            LibraryReference.objects.using(db_alias)
            .filter(hash_key=ref.hash_key)
            .first()
        )
        if not lib:
            lib = LibraryReference.objects.using(db_alias).create(
                hash_key=ref.hash_key,
                source_identifier=ref.source_identifier,
                title=ref.title,
                abstract=ref.abstract,
                authors=ref.authors,
                publication_year=ref.publication_year,
                journal=ref.journal,
                volume=ref.volume,
                issue=ref.issue,
                pages=ref.pages,
                doi=ref.doi,
                url=ref.url,
                language=ref.language,
                raw_ris=ref.raw_ris or {},
                reference_document=ref.reference_document,
                reference_document_uploaded_at=ref.reference_document_uploaded_at,
            )
        ref.library_reference_id = lib.id
        ref.save(update_fields=["library_reference"])


def backwards_unlink_library_references(apps, schema_editor):
    Reference = apps.get_model("synopsis", "Reference")
    db_alias = schema_editor.connection.alias
    Reference.objects.using(db_alias).update(library_reference=None)


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0075_funder_organisation_details"),
    ]

    operations = [
        migrations.CreateModel(
            name="LibraryImportBatch",
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
                (
                    "label",
                    models.CharField(
                        help_text="Short identifier shown to authors (e.g. 'EndNote 2018-2024').",
                        max_length=255,
                    ),
                ),
                (
                    "source_type",
                    models.CharField(
                        choices=[
                            ("journal_search", "Journal / database search"),
                            ("grey_literature", "Grey literature search"),
                            ("non_english", "Non-English search"),
                            ("manual_upload", "Manual upload"),
                            ("library_link", "Library link"),
                            ("legacy", "Legacy import"),
                        ],
                        max_length=40,
                    ),
                ),
                ("search_date_start", models.DateField(blank=True, null=True)),
                ("search_date_end", models.DateField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("original_filename", models.CharField(blank=True, max_length=255)),
                ("record_count", models.PositiveIntegerField(default=0)),
                (
                    "ris_sha1",
                    models.CharField(
                        blank=True,
                        help_text="SHA1 fingerprint of the original RIS payload for deduplication.",
                        max_length=40,
                    ),
                ),
                ("notes", models.TextField(blank=True)),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="uploaded_library_batches",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "library batch",
                "verbose_name_plural": "library batches",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="LibraryReference",
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
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "hash_key",
                    models.CharField(
                        db_index=True,
                        help_text="HASH used to detect duplicates within the library.",
                        max_length=40,
                    ),
                ),
                (
                    "source_identifier",
                    models.CharField(
                        blank=True,
                        help_text="Identifier from the source import (e.g. RefID or Accession number).",
                        max_length=255,
                    ),
                ),
                ("title", models.TextField()),
                ("abstract", models.TextField(blank=True)),
                ("authors", models.TextField(blank=True)),
                ("publication_year", models.PositiveIntegerField(blank=True, null=True)),
                ("journal", models.CharField(blank=True, max_length=255)),
                ("volume", models.CharField(blank=True, max_length=50)),
                ("issue", models.CharField(blank=True, max_length=50)),
                ("pages", models.CharField(blank=True, max_length=50)),
                ("doi", models.CharField(blank=True, max_length=255)),
                ("url", models.URLField(blank=True)),
                ("language", models.CharField(blank=True, max_length=50)),
                (
                    "raw_ris",
                    models.JSONField(
                        blank=True,
                        default=dict,
                        help_text="Original import key/value pairs for full fidelity storage.",
                    ),
                ),
                (
                    "raw_source",
                    models.TextField(
                        blank=True,
                        help_text="Original raw record payload (e.g. EndNote XML).",
                    ),
                ),
                ("raw_source_format", models.CharField(blank=True, max_length=50)),
                (
                    "reference_document",
                    models.FileField(
                        blank=True,
                        help_text="Optional uploaded PDF of the reference.",
                        null=True,
                        upload_to="reference_documents/%Y/%m/%d",
                        validators=[django.core.validators.FileExtensionValidator(["pdf"])],
                    ),
                ),
                ("reference_document_uploaded_at", models.DateTimeField(blank=True, null=True)),
                (
                    "import_batch",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="references",
                        to="synopsis.libraryimportbatch",
                    ),
                ),
            ],
            options={
                "ordering": ["title"],
            },
        ),
        migrations.AddField(
            model_name="reference",
            name="library_reference",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="project_references",
                to="synopsis.libraryreference",
            ),
        ),
        migrations.AddField(
            model_name="reference",
            name="reference_folder",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text="List of CE subject folders assigned to this reference.",
            ),
        ),
        migrations.RunPython(forwards_link_library_references, backwards_unlink_library_references),
    ]
