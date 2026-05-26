from django.db import migrations, models


def _backfill_custom_synopsis_draft_mode(apps, schema_editor):
    ReferenceSummary = apps.get_model("synopsis", "ReferenceSummary")
    batch_size = 500
    pending_ids = []
    summaries = ReferenceSummary.objects.exclude(synopsis_draft="")

    def _flush():
        nonlocal pending_ids
        if not pending_ids:
            return
        ReferenceSummary.objects.filter(pk__in=pending_ids).update(
            use_custom_synopsis_draft=True
        )
        pending_ids = []

    for summary in summaries.iterator(chunk_size=batch_size):
        if (summary.synopsis_draft or "").strip():
            pending_ids.append(summary.pk)
            if len(pending_ids) >= batch_size:
                _flush()
    _flush()


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
