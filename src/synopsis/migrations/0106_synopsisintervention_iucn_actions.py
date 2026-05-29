from django.db import migrations, models


def _copy_iucn_category_to_actions(apps, schema_editor):
    SynopsisIntervention = apps.get_model("synopsis", "SynopsisIntervention")
    ThroughModel = SynopsisIntervention.iucn_actions.through

    batch = []
    for intervention in SynopsisIntervention.objects.exclude(
        iucn_category_id__isnull=True
    ).iterator(chunk_size=500):
        batch.append(
            ThroughModel(
                synopsisintervention_id=intervention.id,
                iucncategory_id=intervention.iucn_category_id,
            )
        )
        if len(batch) >= 500:
            ThroughModel.objects.bulk_create(batch, ignore_conflicts=True)
            batch.clear()
    if batch:
        ThroughModel.objects.bulk_create(batch, ignore_conflicts=True)


def _copy_iucn_actions_to_category(apps, schema_editor):
    SynopsisIntervention = apps.get_model("synopsis", "SynopsisIntervention")
    ThroughModel = SynopsisIntervention.iucn_actions.through

    for intervention in SynopsisIntervention.objects.all().iterator(chunk_size=500):
        first_link = (
            ThroughModel.objects.filter(synopsisintervention_id=intervention.id)
            .order_by("iucncategory_id")
            .first()
        )
        intervention.iucn_category_id = (
            first_link.iucncategory_id if first_link else None
        )
        intervention.save(update_fields=["iucn_category"])


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0105_alter_synopsisinterventionkeymessage_response_group"),
    ]

    operations = [
        migrations.AddField(
            model_name="synopsisintervention",
            name="iucn_actions",
            field=models.ManyToManyField(
                blank=True,
                related_name="synopsis_interventions",
                to="synopsis.iucncategory",
            ),
        ),
        migrations.RunPython(
            _copy_iucn_category_to_actions,
            reverse_code=_copy_iucn_actions_to_category,
        ),
        migrations.RemoveField(
            model_name="synopsisintervention",
            name="iucn_category",
        ),
    ]
