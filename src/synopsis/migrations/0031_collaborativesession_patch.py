from django.db import migrations


def forwards(apps, schema_editor):
    table = 'synopsis_collaborativesession'
    connection = schema_editor.connection
    if connection.vendor != 'postgresql':
        # Raw SQL uses PostgreSQL catalogs; skip on other databases.
        return
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = %s
            """,
            [table],
        )
        columns = {row[0] for row in cursor.fetchall()}

    def add_column_sql(sql, *, update=None, drop_default=False):
        schema_editor.execute(sql)
        if update:
            schema_editor.execute(update)
        if drop_default:
            schema_editor.execute("ALTER TABLE %s ALTER COLUMN %s DROP DEFAULT" % (table, drop_default))

    if 'last_activity_at' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN last_activity_at timestamp with time zone",
            update=f"UPDATE {table} SET last_activity_at = started_at",
        )
    if 'ended_at' not in columns:
        add_column_sql(f"ALTER TABLE {table} ADD COLUMN ended_at timestamp with time zone")
    if 'ended_by_id' not in columns:
        add_column_sql(f"ALTER TABLE {table} ADD COLUMN ended_by_id integer")
    if 'end_reason' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN end_reason varchar(255) NOT NULL DEFAULT ''",
            drop_default='end_reason',
        )
    if 'change_summary' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN change_summary text NOT NULL DEFAULT ''",
            drop_default='change_summary',
        )
    if 'last_callback_payload' not in columns:
        add_column_sql(f"ALTER TABLE {table} ADD COLUMN last_callback_payload jsonb")
    if 'initial_protocol_revision_id' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN initial_protocol_revision_id bigint")
    if 'initial_action_list_revision_id' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN initial_action_list_revision_id bigint")
    if 'result_protocol_revision_id' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN result_protocol_revision_id bigint")
    if 'result_action_list_revision_id' not in columns:
        add_column_sql(
            f"ALTER TABLE {table} ADD COLUMN result_action_list_revision_id bigint")

    # drop legacy columns if they exist
    legacy_columns = ['cancelled_at', 'completed_at', 'expires_at', 'notes', 'initial_revision_id', 'resulting_revision_id']
    for legacy in legacy_columns:
        if legacy in columns:
            schema_editor.execute(f"ALTER TABLE {table} DROP COLUMN {legacy} CASCADE")

    def add_fk(name, sql):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = %s",
                [name],
            )
            exists = cursor.fetchone()
        if not exists:
            schema_editor.execute(sql)

    add_fk(
        'collab_session_ended_by_fk',
        f"ALTER TABLE {table} ADD CONSTRAINT collab_session_ended_by_fk FOREIGN KEY (ended_by_id) REFERENCES auth_user(id) DEFERRABLE INITIALLY DEFERRED",
    )
    add_fk(
        'collab_session_initial_protocol_fk',
        f"ALTER TABLE {table} ADD CONSTRAINT collab_session_initial_protocol_fk FOREIGN KEY (initial_protocol_revision_id) REFERENCES synopsis_protocolrevision(id) DEFERRABLE INITIALLY DEFERRED",
    )
    add_fk(
        'collab_session_initial_action_fk',
        f"ALTER TABLE {table} ADD CONSTRAINT collab_session_initial_action_fk FOREIGN KEY (initial_action_list_revision_id) REFERENCES synopsis_actionlistrevision(id) DEFERRABLE INITIALLY DEFERRED",
    )
    add_fk(
        'collab_session_result_protocol_fk',
        f"ALTER TABLE {table} ADD CONSTRAINT collab_session_result_protocol_fk FOREIGN KEY (result_protocol_revision_id) REFERENCES synopsis_protocolrevision(id) DEFERRABLE INITIALLY DEFERRED",
    )
    add_fk(
        'collab_session_result_action_fk',
        f"ALTER TABLE {table} ADD CONSTRAINT collab_session_result_action_fk FOREIGN KEY (result_action_list_revision_id) REFERENCES synopsis_actionlistrevision(id) DEFERRABLE INITIALLY DEFERRED",
    )


def backwards(apps, schema_editor):
    # Non-destructive reverse not implemented.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('synopsis', '0030_collaborativesession'),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
