from django.db import migrations


def drop_pilot_guidance_tables_and_columns(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    quote = schema_editor.quote_name
    orphan_columns = {
        "synopsis_advisoryboardmember": [
            "action_list_feedback_on_guidance",
            "added_to_guidance_doc",
            "feedback_on_guidance_deadline",
            "feedback_on_guidance_received",
            "guidance_author_replied",
            "guidance_reminder_sent",
            "guidance_reminder_sent_at",
            "sent_guidance_at",
        ],
        "synopsis_collaborativesession": [
            "initial_guidance_revision_id",
            "result_guidance_revision_id",
        ],
    }
    for table, columns in orphan_columns.items():
        for column in columns:
            schema_editor.execute(
                f"ALTER TABLE {quote(table)} DROP COLUMN IF EXISTS {quote(column)} CASCADE"
            )

    for table in [
        "synopsis_guidancefeedback",
        "synopsis_guidancerevision",
        "synopsis_guidance",
    ]:
        schema_editor.execute(f"DROP TABLE IF EXISTS {quote(table)} CASCADE")


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0097_advisoryboardmember_document_author_replied_flags"),
    ]

    operations = [
        migrations.RunPython(
            drop_pilot_guidance_tables_and_columns,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.RemoveField(
            model_name="advisoryboardmember",
            name="feedback_on_guidance",
        ),
    ]
