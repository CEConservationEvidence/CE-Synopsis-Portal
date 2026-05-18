from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0096_libraryreference_reference_folder_and_history"),
    ]

    operations = [
        migrations.AddField(
            model_name="advisoryboardmember",
            name="protocol_author_replied",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="advisoryboardmember",
            name="synopsis_author_replied",
            field=models.BooleanField(default=False),
        ),
    ]
