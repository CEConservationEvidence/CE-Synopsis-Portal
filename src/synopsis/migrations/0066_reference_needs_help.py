from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0065_comment_threading"),
    ]

    operations = [
        migrations.AddField(
            model_name="reference",
            name="needs_help",
            field=models.BooleanField(default=False),
        ),
    ]
