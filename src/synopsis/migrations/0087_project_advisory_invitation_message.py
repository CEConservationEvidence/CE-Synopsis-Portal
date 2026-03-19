from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0086_rename_advisoryboardmember_location_to_country"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="advisory_invitation_message",
            field=models.TextField(blank=True, default=""),
        ),
    ]
