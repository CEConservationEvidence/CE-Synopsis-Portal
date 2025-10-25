from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0037_advisoryboardmember_added_to_synopsis_doc_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="advisoryboardcustomfield",
            name="display_group",
            field=models.CharField(
                choices=[
                    ("personal", "Personal details"),
                    ("invitation", "Invitation"),
                    ("action", "Action list"),
                    ("protocol", "Protocol"),
                    ("synopsis", "Synopsis"),
                    ("custom", "Custom section"),
                ],
                default="custom",
                help_text="Choose where this column should appear in the advisory board table.",
                max_length=20,
            ),
        ),
    ]
