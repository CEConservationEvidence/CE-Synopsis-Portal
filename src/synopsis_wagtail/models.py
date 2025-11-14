from django.db import models
from wagtail.fields import RichTextField, StreamField
from wagtail.admin.panels import FieldPanel
from wagtail import blocks
from wagtail.models import Page
from wagtail.snippets.blocks import SnippetChooserBlock

from synopsis.models import Project, SynopsisOutlineChapter, SynopsisOutlineSection


class ReferenceSummaryBlock(blocks.StructBlock):
    summary = SnippetChooserBlock("synopsis.ReferenceSummary", label="Summary")

    class Meta:
        template = "synopsis_wagtail/blocks/reference_summary.html"
        icon = "doc-full"
        label = "Reference summary"


class ChapterStreamBlock(blocks.StreamBlock):
    heading = blocks.CharBlock(form_classname="title", label="Heading")
    paragraph = blocks.RichTextBlock(
        features=["h3", "bold", "italic", "ol", "ul", "link"], label="Paragraph"
    )
    quote = blocks.BlockQuoteBlock()
    reference_summary = ReferenceSummaryBlock()


class SynopsisIndexPage(Page):
    subpage_types = ["synopsis_wagtail.SynopsisProjectPage"]
    parent_page_types = ["wagtailcore.Page"]
    max_count = 1


class SynopsisProjectPage(Page):
    project = models.OneToOneField(
        Project,
        on_delete=models.PROTECT,
        related_name="synopsis_page",
        editable=False,
    )
    introduction = RichTextField(blank=True)

    parent_page_types = ["synopsis_wagtail.SynopsisIndexPage"]
    subpage_types = ["synopsis_wagtail.SynopsisChapterPage"]

    content_panels = Page.content_panels + [FieldPanel("introduction")]


class SynopsisChapterPage(Page):
    summary = RichTextField(blank=True)
    body = StreamField(ChapterStreamBlock(), use_json_field=True, blank=True)

    parent_page_types = ["synopsis_wagtail.SynopsisProjectPage"]
    subpage_types = []

    content_panels = Page.content_panels + [
        FieldPanel("summary"),
        FieldPanel("body"),
    ]

    def get_outline_blocks(self):
        try:
            chapter = self.outline_chapter
        except SynopsisOutlineChapter.DoesNotExist:
            return []
        return list(
            chapter.blocks.select_related("reference_summary", "section").order_by(
                "position", "id"
            )
        )

    def get_outline_section_meta(self, section_id):
        if not section_id:
            return None
        if not hasattr(self, "_outline_section_map"):
            try:
                chapter = self.outline_chapter
            except SynopsisOutlineChapter.DoesNotExist:
                self._outline_section_map = {}
            else:
                self._outline_section_map = {
                    section.id: section for section in chapter.sections.all()
                }
        return self._outline_section_map.get(section_id)
