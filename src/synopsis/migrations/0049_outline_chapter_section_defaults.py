from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0048_outline_sections_structure"),
    ]

    operations = [
        migrations.AlterField(
            model_name="synopsisoutlinechapter",
            name="section_type",
            field=models.CharField(
                choices=[
                    ("front_matter", "Front matter"),
                    ("threat", "Threat"),
                    ("action", "Action group"),
                    ("appendix", "Appendix"),
                ],
                default="action",
                max_length=20,
            ),
        ),
    ]
