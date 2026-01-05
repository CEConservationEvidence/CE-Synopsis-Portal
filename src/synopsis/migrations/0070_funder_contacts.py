from django.db import migrations, models


def create_primary_contacts(apps, schema_editor):
    Funder = apps.get_model("synopsis", "Funder")
    FunderContact = apps.get_model("synopsis", "FunderContact")
    contacts = []
    for funder in Funder.objects.all():
        if funder.contact_first_name or funder.contact_last_name or funder.contact_title:
            contacts.append(
                FunderContact(
                    funder=funder,
                    title=funder.contact_title,
                    first_name=funder.contact_first_name,
                    last_name=funder.contact_last_name,
                    email="",
                    is_primary=True,
                )
            )
    if contacts:
        FunderContact.objects.bulk_create(contacts)


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0069_restore_reference_needs_help"),
    ]

    operations = [
        migrations.CreateModel(
            name="FunderContact",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("title", models.CharField(blank=True, max_length=50)),
                ("first_name", models.CharField(blank=True, max_length=100)),
                ("last_name", models.CharField(blank=True, max_length=100)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("is_primary", models.BooleanField(default=False)),
                (
                    "funder",
                    models.ForeignKey(
                        on_delete=models.CASCADE,
                        related_name="contacts",
                        to="synopsis.funder",
                    ),
                ),
            ],
            options={
                "ordering": ["-is_primary", "id"],
            },
        ),
        migrations.AddConstraint(
            model_name="fundercontact",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_primary", True)),
                fields=("funder",),
                name="unique_primary_contact_per_funder",
            ),
        ),
        migrations.RunPython(create_primary_contacts, migrations.RunPython.noop),
    ]
