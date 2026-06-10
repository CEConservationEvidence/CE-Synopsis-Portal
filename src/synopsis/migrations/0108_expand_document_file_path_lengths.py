from django.db import migrations, models
import synopsis.models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0107_project_saved_action_names"),
    ]

    operations = [
        migrations.AlterField(
            model_name="protocol",
            name="document",
            field=models.FileField(
                max_length=255, upload_to=synopsis.models.protocol_upload_path
            ),
        ),
        migrations.AlterField(
            model_name="protocolrevision",
            name="file",
            field=models.FileField(
                max_length=255, upload_to=synopsis.models.protocol_revision_upload_path
            ),
        ),
        migrations.AlterField(
            model_name="actionlist",
            name="document",
            field=models.FileField(
                max_length=255, upload_to=synopsis.models.action_list_upload_path
            ),
        ),
        migrations.AlterField(
            model_name="actionlistrevision",
            name="file",
            field=models.FileField(
                max_length=255,
                upload_to=synopsis.models.action_list_revision_upload_path,
            ),
        ),
    ]
