from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0061_rebuild_synopsis_structure"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesummary",
            name="summary_author",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="referencesummary",
            name="broad_category",
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name="referencesummary",
            name="keywords",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="referencesummary",
            name="source_url",
            field=models.URLField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name="referencesummary",
            name="crop_type",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
