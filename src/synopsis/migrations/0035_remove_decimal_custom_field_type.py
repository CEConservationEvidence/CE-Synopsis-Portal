from django.db import migrations, models


def migrate_decimal_to_text(apps, schema_editor):
    CustomField = apps.get_model("synopsis", "AdvisoryBoardCustomField")
    CustomField.objects.filter(data_type="decimal").update(data_type="text")


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0034_advisoryboardcustomfield_and_more"),
    ]

    operations = [
        migrations.RunPython(migrate_decimal_to_text, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="advisoryboardcustomfield",
            name="data_type",
            field=models.CharField(
                choices=[
                    ("text", "Text"),
                    ("integer", "Integer"),
                    ("boolean", "Yes / No"),
                    ("date", "Date"),
                ],
                default="text",
                max_length=20,
            ),
        ),
    ]
