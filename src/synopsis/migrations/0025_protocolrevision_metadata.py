from django.db import migrations
import os


def populate_revision_metadata(apps, schema_editor):
    ProtocolRevision = apps.get_model("synopsis", "ProtocolRevision")

    for revision in ProtocolRevision.objects.all():
        needs_update = False
        if not getattr(revision, "original_name", ""):
            revision.original_name = os.path.basename(revision.file.name)
            needs_update = True
        file_size = getattr(revision, "file_size", 0)
        try:
            actual_size = revision.file.size if revision.file else 0
        except FileNotFoundError:
            actual_size = 0
        if not file_size and actual_size:
            revision.file_size = actual_size
            needs_update = True
        if needs_update:
            revision.save(update_fields=["original_name", "file_size"])


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0024_protocolrevision_protocol_current_revision"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE synopsis_protocolrevision
            ADD COLUMN IF NOT EXISTS original_name varchar(255) DEFAULT '';
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql="""
            ALTER TABLE synopsis_protocolrevision
            ADD COLUMN IF NOT EXISTS file_size bigint DEFAULT 0;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunPython(populate_revision_metadata, migrations.RunPython.noop),
    ]
