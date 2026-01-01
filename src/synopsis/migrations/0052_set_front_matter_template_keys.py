from django.db import migrations

FRONT_MATTER_TITLES = {
    "front_matter_advisory_board": "Advisory Board",
    "front_matter_authors": "About the authors",
    "front_matter_acknowledgements": "Acknowledgements",
    "front_matter_about": "About this book",
}


def assign_keys(apps, schema_editor):
    Chapter = apps.get_model("synopsis", "SynopsisOutlineChapter")
    for key, title in FRONT_MATTER_TITLES.items():
        for chapter in Chapter.objects.filter(title=title, section_type="front_matter"):
            if not chapter.template_key:
                chapter.template_key = key
                chapter.save(update_fields=["template_key"])


def unassign_keys(apps, schema_editor):
    Chapter = apps.get_model("synopsis", "SynopsisOutlineChapter")
    Chapter.objects.filter(template_key__in=FRONT_MATTER_TITLES.keys()).update(template_key="")


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis", "0051_synopsisoutlinechapter_template_key"),
    ]

    operations = [
        migrations.RunPython(assign_keys, unassign_keys),
    ]
