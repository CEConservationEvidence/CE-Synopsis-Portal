from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0081_synopsisintervention_ce_action_url_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="synopsisinterventionkeymessage",
            name="supporting_summaries",
            field=models.ManyToManyField(
                blank=True,
                help_text="Optional subset of assigned study summaries that support this key message.",
                related_name="supporting_key_messages",
                to="synopsis.referencesummary",
            ),
        ),
    ]
