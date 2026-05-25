from django.db import migrations, models


def _backfill_custom_synopsis_draft_mode(apps, schema_editor):
    ReferenceSummary = apps.get_model("synopsis", "ReferenceSummary")
    summaries = ReferenceSummary.objects.exclude(synopsis_draft="")
    for summary in summaries.iterator(chunk_size=500):
        if (summary.synopsis_draft or "").strip():
            ReferenceSummary.objects.filter(pk=summary.pk).update(
                use_custom_synopsis_draft=True
            )


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0101_repair_reference_unlinked_folder_column"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesummary",
            name="use_custom_synopsis_draft",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(
            _backfill_custom_synopsis_draft_mode, migrations.RunPython.noop
        ),
    ]
