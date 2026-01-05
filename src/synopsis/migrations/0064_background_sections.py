from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0063_merge"),
    ]

    operations = [
        migrations.AddField(
            model_name="synopsischapter",
            name="background_references",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="synopsischapter",
            name="background_text",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="synopsisintervention",
            name="background_references",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="synopsisintervention",
            name="background_text",
            field=models.TextField(blank=True),
        ),
    ]
