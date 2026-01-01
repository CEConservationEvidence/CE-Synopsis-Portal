from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0047_referenceactionsummary_outlineblock_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="synopsisoutlinechapter",
            name="section_number",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="synopsisoutlinechapter",
            name="section_type",
            field=models.CharField(
                choices=[
                    ("front_matter", "Front matter"),
                    ("threat", "Threat"),
                    ("action", "Action group"),
                    ("appendix", "Appendix"),
                ],
                default="front_matter",
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name="SynopsisOutlineSection",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=255)),
                ("position", models.PositiveIntegerField(default=0)),
                ("number_label", models.CharField(blank=True, max_length=20)),
                (
                    "chapter",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="sections",
                        to="synopsis.synopsisoutlinechapter",
                    ),
                ),
            ],
            options={
                "ordering": ["position", "id"],
            },
        ),
        migrations.AddField(
            model_name="synopsisoutlineblock",
            name="section",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="blocks",
                to="synopsis.synopsisoutlinesection",
            ),
        ),
    ]
