from django.db import migrations


def create_synopsis_index(apps, schema_editor):
    from wagtail.models import Page, Site
    from synopsis_wagtail.models import SynopsisIndexPage

    root = Page.get_first_root_node()
    if not SynopsisIndexPage.objects.exists():
        index_page = SynopsisIndexPage(
            title="Synopsis Workspace",
            slug="synopsis-workspace",
        )
        root.add_child(instance=index_page)
        index_page.save_revision().publish()
    else:
        index_page = SynopsisIndexPage.objects.first()

    if not Site.objects.filter(is_default_site=True).exists():
        Site.objects.create(
            hostname="localhost",
            site_name="CE Synopsis Writer",
            root_page=index_page,
            is_default_site=True,
        )
    else:
        site = Site.objects.order_by("-is_default_site").first()
        if site.root_page_id != index_page.id:
            site.root_page = index_page
            site.save()


def remove_synopsis_index(apps, schema_editor):
    from synopsis_wagtail.models import SynopsisIndexPage

    SynopsisIndexPage.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis_wagtail", "0001_initial"),
        ("wagtailsearch", "0006_customise_indexentry"),
    ]

    operations = [
        migrations.RunPython(create_synopsis_index, remove_synopsis_index),
    ]
