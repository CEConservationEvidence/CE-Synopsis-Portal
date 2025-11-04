from django.db import migrations


def simplify_statuses(apps, schema_editor):
    Reference = apps.get_model("synopsis", "Reference")

    include_statuses = [
        "title_included",
        "fulltext_included",
    ]
    exclude_statuses = [
        "title_excluded",
        "fulltext_excluded",
    ]

    Reference.objects.filter(
        screening_status__in=include_statuses
    ).update(screening_status="included")
    Reference.objects.filter(
        screening_status__in=exclude_statuses
    ).update(screening_status="excluded")
    Reference.objects.filter(
        screening_status="needs_full_text"
    ).update(screening_status="pending")


def revert_statuses(apps, schema_editor):
    Reference = apps.get_model("synopsis", "Reference")

    Reference.objects.filter(
        screening_status="included"
    ).update(screening_status="title_included")
    Reference.objects.filter(
        screening_status="excluded"
    ).update(screening_status="title_excluded")


class Migration(migrations.Migration):
    dependencies = [
        ("synopsis", "0038_advisoryboardcustomfield_display_group"),
    ]

    operations = [
        migrations.RunPython(simplify_statuses, revert_statuses),
    ]
