from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "synopsis",
            "0094_project_protocol_relevant_project_advisory_board_relevant",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesummary",
            name="exclusion_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name="referencesummary",
            name="status",
            field=models.CharField(
                choices=[
                    ("todo", "To summarise"),
                    ("draft", "In progress"),
                    ("review", "Needs review/help"),
                    ("done", "Summarised"),
                    ("excluded", "Excluded after full text"),
                ],
                default="todo",
                max_length=20,
            ),
        ),
    ]
