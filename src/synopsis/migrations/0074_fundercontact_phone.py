from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0073_enforce_primary_contact_unique"),
    ]

    operations = [
        migrations.AddField(
            model_name="fundercontact",
            name="phone",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
