from django.db import migrations, models

import synopsis.models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0090_advisoryboardmember_action_list_feedback_on_guidance"),
    ]

    operations = [
        migrations.AlterField(
            model_name="protocol",
            name="document",
            field=models.FileField(upload_to=synopsis.models.protocol_upload_path),
        ),
    ]
