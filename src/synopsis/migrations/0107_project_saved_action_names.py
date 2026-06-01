from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0106_synopsisintervention_iucn_actions"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="saved_action_names",
            field=models.TextField(blank=True, default=""),
        ),
    ]
