from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0050_alter_synopsisoutlinechapter_section_type"),
    ]

    operations = [
        migrations.AddField(
            model_name="synopsisoutlinechapter",
            name="template_key",
            field=models.CharField(blank=True, max_length=50),
        ),
    ]
