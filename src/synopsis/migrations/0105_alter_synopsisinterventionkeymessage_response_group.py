from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0104_remove_synopsisintervention_synthesis_text"),
    ]

    operations = [
        migrations.AlterField(
            model_name="synopsisinterventionkeymessage",
            name="response_group",
            field=models.CharField(
                choices=[
                    ("community", "Community response"),
                    ("population", "Population response"),
                    ("behaviour", "Behaviour"),
                    ("response", "General response"),
                    ("vegetation_community", "Vegetation Community"),
                    ("vegetation_abundance", "Vegetation Abundance"),
                    ("vegetation_structure", "Vegetation Structure"),
                    ("other", "Other"),
                ],
                default="response",
                max_length=20,
            ),
        ),
    ]
