from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0043_alter_reference_screening_status_referencesummary_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesummary",
            name="synopsis_draft",
            field=models.TextField(blank=True),
        ),
    ]
