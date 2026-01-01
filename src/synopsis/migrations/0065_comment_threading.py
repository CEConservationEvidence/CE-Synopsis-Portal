from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0064_background_sections"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencesummarycomment",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=models.CASCADE,
                related_name="replies",
                to="synopsis.referencesummarycomment",
            ),
        ),
        migrations.AddField(
            model_name="referencesummarycomment",
            name="attachment",
            field=models.FileField(blank=True, upload_to="summary_comments/"),
        ),
        migrations.AddField(
            model_name="referencesummarycomment",
            name="notify_assignee",
            field=models.BooleanField(default=False),
        ),
        migrations.AlterModelOptions(
            name="referencesummarycomment",
            options={"ordering": ["-created_at", "-id"]},
        ),
    ]
