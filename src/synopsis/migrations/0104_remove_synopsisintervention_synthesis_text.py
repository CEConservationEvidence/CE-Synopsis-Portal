from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0103_referencesummary_paragraph_notes"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="synopsisintervention",
            name="synthesis_text",
        ),
    ]
