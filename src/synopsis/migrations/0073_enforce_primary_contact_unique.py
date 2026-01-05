from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0072_patch_funder_contacts"),
    ]

    operations = [
        migrations.RunSQL(
            sql=(
                "CREATE UNIQUE INDEX IF NOT EXISTS unique_primary_contact_per_funder "
                "ON synopsis_fundercontact (funder_id) WHERE is_primary;"
            ),
            reverse_sql="DROP INDEX IF EXISTS unique_primary_contact_per_funder;",
        ),
    ]
