from django.db import migrations


def _column_names(schema_editor, table_name):
    with schema_editor.connection.cursor() as cursor:
        description = schema_editor.connection.introspection.get_table_description(
            cursor, table_name
        )
    return {column.name for column in description}


def repair_reference_folder_column(apps, schema_editor):
    table_name = "synopsis_reference"
    columns = _column_names(schema_editor, table_name)
    if "reference_folder" in columns and "unlinked_reference_folder" not in columns:
        schema_editor.execute(
            "ALTER TABLE synopsis_reference "
            "RENAME COLUMN reference_folder TO unlinked_reference_folder"
        )


def reverse_repair_reference_folder_column(apps, schema_editor):
    table_name = "synopsis_reference"
    columns = _column_names(schema_editor, table_name)
    if "unlinked_reference_folder" in columns and "reference_folder" not in columns:
        schema_editor.execute(
            "ALTER TABLE synopsis_reference "
            "RENAME COLUMN unlinked_reference_folder TO reference_folder"
        )


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0100_reference_category_single_source_state"),
    ]

    operations = [
        migrations.RunPython(
            repair_reference_folder_column,
            reverse_repair_reference_folder_column,
        ),
    ]
