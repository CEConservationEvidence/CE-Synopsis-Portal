from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0089_project_description"),
    ]

    operations = [
        migrations.AddField(
            model_name="advisoryboardmember",
            name="action_list_feedback_on_guidance",
            field=models.BooleanField(default=False),
        ),
    ]
