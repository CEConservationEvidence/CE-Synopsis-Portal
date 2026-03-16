from django.db import migrations


def add_missing_library_reference_columns(apps, schema_editor):
    connection = schema_editor.connection
    table_name = "synopsis_libraryreference"
    with connection.cursor() as cursor:
        existing_columns = {
            column.name
            for column in connection.introspection.get_table_description(cursor, table_name)
        }

    statements = []
    vendor = connection.vendor

    if "raw_source" not in existing_columns:
        if vendor == "mysql":
            column_type = "longtext"
        else:
            column_type = "text"
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN raw_source {column_type}"
        )

    if "raw_source_format" not in existing_columns:
        statements.append(
            f"ALTER TABLE {table_name} ADD COLUMN raw_source_format varchar(50)"
        )

    for statement in statements:
        schema_editor.execute(statement)


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0077_alter_reference_raw_ris_and_more"),
    ]

    operations = [
        migrations.RunPython(
            add_missing_library_reference_columns,
            migrations.RunPython.noop,
        ),
    ]
