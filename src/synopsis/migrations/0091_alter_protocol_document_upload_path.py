from django.db import migrations, models

import synopsis.models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0089_project_description"),
    ]

    operations = [
        migrations.AlterField(
            model_name="protocol",
            name="document",
            field=models.FileField(upload_to=synopsis.models.protocol_upload_path),
        ),
    ]
