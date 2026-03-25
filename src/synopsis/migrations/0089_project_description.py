from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0088_update_iucn_action_categories"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
    ]
