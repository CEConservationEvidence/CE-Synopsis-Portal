from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0085_dedupe_libraryreference_hashes_and_enforce_unique"),
    ]

    operations = [
        migrations.RenameField(
            model_name="advisoryboardmember",
            old_name="location",
            new_name="country",
        ),
    ]
