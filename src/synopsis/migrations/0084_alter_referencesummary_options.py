from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0083_alter_referencesummary_reference"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="referencesummary",
            options={"ordering": ["reference__title", "created_at", "id"]},
        ),
    ]
