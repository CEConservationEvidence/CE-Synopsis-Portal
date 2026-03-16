from django.db import migrations, models
from django.db.models import Count


def _is_empty(value):
    if value is None:
        return True
    if value == "":
        return True
    if value == {}:
        return True
    if value == []:
        return True
    return False


def dedupe_library_reference_hashes(apps, schema_editor):
    LibraryReference = apps.get_model("synopsis", "LibraryReference")
    Reference = apps.get_model("synopsis", "Reference")
    db_alias = schema_editor.connection.alias

    duplicate_hashes = (
        LibraryReference.objects.using(db_alias)
        .values("hash_key")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )

    merge_fields = [
        "import_batch_id",
        "source_identifier",
        "abstract",
        "authors",
        "publication_year",
        "journal",
        "volume",
        "issue",
        "pages",
        "doi",
        "url",
        "language",
        "raw_ris",
        "raw_source",
        "raw_source_format",
        "reference_document",
        "reference_document_uploaded_at",
    ]

    for row in duplicate_hashes.iterator():
        duplicates = list(
            LibraryReference.objects.using(db_alias)
            .filter(hash_key=row["hash_key"])
            .order_by("id")
        )
        keeper = duplicates[0]
        keeper_changed = False

        for duplicate in duplicates[1:]:
            for field_name in merge_fields:
                keeper_value = getattr(keeper, field_name)
                duplicate_value = getattr(duplicate, field_name)
                if _is_empty(keeper_value) and not _is_empty(duplicate_value):
                    setattr(keeper, field_name, duplicate_value)
                    keeper_changed = True

            Reference.objects.using(db_alias).filter(
                library_reference_id=duplicate.id
            ).update(library_reference_id=keeper.id)
            duplicate.delete()

        if keeper_changed:
            keeper.save()


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0084_alter_referencesummary_options"),
    ]

    operations = [
        migrations.RunPython(dedupe_library_reference_hashes, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="libraryreference",
            name="hash_key",
            field=models.CharField(
                help_text="HASH used to detect duplicates within the library.",
                max_length=40,
                unique=True,
            ),
        ),
    ]
