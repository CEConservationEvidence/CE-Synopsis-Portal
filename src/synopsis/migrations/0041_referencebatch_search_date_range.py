from django.db import migrations, models


def forward_copy_search_dates(apps, schema_editor):
    ReferenceSourceBatch = apps.get_model("synopsis", "ReferenceSourceBatch")
    for batch in ReferenceSourceBatch.objects.all():
        date = getattr(batch, "search_date", None)
        if date:
            batch.search_date_start = date
            batch.search_date_end = date
            batch.save(
                update_fields=["search_date_start", "search_date_end"]
            )


def reverse_copy_search_dates(apps, schema_editor):
    ReferenceSourceBatch = apps.get_model("synopsis", "ReferenceSourceBatch")
    for batch in ReferenceSourceBatch.objects.all():
        date = batch.search_date_start or batch.search_date_end
        batch.search_date = date
        batch.save(update_fields=["search_date"])


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0040_reference_screening_status_simplify"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesourcebatch",
            name="search_date_end",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="referencesourcebatch",
            name="search_date_start",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.RunPython(
            forward_copy_search_dates, reverse_copy_search_dates
        ),
        migrations.RemoveField(
            model_name="referencesourcebatch",
            name="search_date",
        ),
    ]

