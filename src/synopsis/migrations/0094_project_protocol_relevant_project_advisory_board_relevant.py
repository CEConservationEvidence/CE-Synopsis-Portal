from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        (
            "synopsis",
            "0093_alter_advisoryboardcustomfield_display_group",
        ),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="advisory_board_relevant",
            field=models.BooleanField(default=True),
        ),
        migrations.AddField(
            model_name="project",
            name="protocol_relevant",
            field=models.BooleanField(default=True),
        ),
    ]
