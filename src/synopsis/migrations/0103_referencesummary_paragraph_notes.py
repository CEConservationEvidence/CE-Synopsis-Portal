from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0102_referencesummary_use_custom_synopsis_draft"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesummary",
            name="paragraph_notes",
            field=models.TextField(blank=True),
        ),
    ]
