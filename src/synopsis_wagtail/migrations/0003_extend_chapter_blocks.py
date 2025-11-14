from django.db import migrations
import wagtail.blocks
import wagtail.fields
import wagtail.snippets.blocks


class Migration(migrations.Migration):

    dependencies = [
        ("synopsis_wagtail", "0002_create_synopsis_index"),
    ]

    operations = [
        migrations.AlterField(
            model_name="synopsischapterpage",
            name="body",
            field=wagtail.fields.StreamField(
                [
                    ("heading", wagtail.blocks.CharBlock(form_classname="title", label="Heading")),
                    (
                        "paragraph",
                        wagtail.blocks.RichTextBlock(
                            features=["h3", "bold", "italic", "ol", "ul", "link"],
                            label="Paragraph",
                        ),
                    ),
                    ("quote", wagtail.blocks.BlockQuoteBlock()),
                    (
                        "reference_summary",
                        wagtail.blocks.StructBlock(
                            [
                                (
                                    "summary",
                                    wagtail.snippets.blocks.SnippetChooserBlock(
                                        "synopsis.ReferenceSummary",
                                        label="Summary",
                                    ),
                                )
                            ],
                            icon="doc-full",
                            label="Reference summary",
                        ),
                    ),
                ],
                blank=True,
                use_json_field=True,
            ),
        ),
    ]
