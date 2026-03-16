from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0082_synopsisinterventionkeymessage_supporting_summaries"),
    ]

    operations = [
        migrations.AlterField(
            model_name="referencesummary",
            name="reference",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="summaries",
                to="synopsis.reference",
            ),
        ),
    ]
