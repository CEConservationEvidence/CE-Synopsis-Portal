from django.db import migrations


def ensure_needs_help(apps, schema_editor):
    """Add needs_help field to reference table only if missing (idempotent)."""
    Reference = apps.get_model("synopsis", "Reference")
    table = Reference._meta.db_table
    connection = schema_editor.connection

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

    if "needs_help" in columns:
        return

    field = Reference._meta.get_field("needs_help")
    schema_editor.add_field(Reference, field)


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0068_alter_referencesummary_status"),
    ]

    operations = [
        migrations.RunPython(ensure_needs_help, migrations.RunPython.noop),
    ]
