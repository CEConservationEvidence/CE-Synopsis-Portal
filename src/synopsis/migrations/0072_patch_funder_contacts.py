from django.db import migrations, models


def ensure_contacts(apps, schema_editor):
    connection = schema_editor.connection
    Funder = apps.get_model("synopsis", "Funder")
    FunderContact = apps.get_model("synopsis", "FunderContact")
    table = FunderContact._meta.db_table

    with connection.cursor() as cursor:
        try:
            columns = {
                col.name
                for col in connection.introspection.get_table_description(
                    cursor, table
                )
            }
        except Exception:
            columns = set()
        if columns and "is_primary" not in columns:
            field = FunderContact._meta.get_field("is_primary")
            schema_editor.add_field(FunderContact, field)

        constraints = {}
        try:
            constraints = connection.introspection.get_constraints(cursor, table)
        except Exception:
            constraints = {}
        if columns and "unique_primary_contact_per_funder" not in constraints:
            schema_editor.add_constraint(
                FunderContact,
                models.UniqueConstraint(
                    fields=["funder"],
                    condition=models.Q(is_primary=True),
                    name="unique_primary_contact_per_funder",
                ),
            )

    for funder in Funder.objects.all():
        existing = FunderContact.objects.filter(funder=funder)
        if existing.exists():
            if not existing.filter(is_primary=True).exists():
                first = existing.order_by("id").first()
                if first:
                    first.is_primary = True
                    first.save(update_fields=["is_primary"])
            continue

        if (
            funder.contact_first_name
            or funder.contact_last_name
            or funder.contact_title
        ):
            FunderContact.objects.create(
                funder=funder,
                title=funder.contact_title,
                first_name=funder.contact_first_name,
                last_name=funder.contact_last_name,
                email="",
                is_primary=True,
            )


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0070_funder_contacts"),
    ]

    operations = [
        migrations.RunPython(ensure_contacts, migrations.RunPython.noop),
    ]
