from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0074_fundercontact_phone"),
    ]

    operations = [
        migrations.AddField(
            model_name="funder",
            name="organisation_details",
            field=models.TextField(blank=True, default=""),
            preserve_default=False,
        ),
    ]
