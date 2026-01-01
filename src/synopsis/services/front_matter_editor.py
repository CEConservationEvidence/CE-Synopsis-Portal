from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from django.db.models import Max
from django.utils.text import slugify

from synopsis.models import SynopsisOutlineBlock, SynopsisOutlineSection
from synopsis.services.outline_templates import FRONT_MATTER_TEMPLATE


@dataclass(frozen=True)
class FrontMatterFieldSpec:
    key: str
    label: str
    help_text: str = ""
    placeholder: str = ""
    rows: int = 6
    section_number: Optional[str] = None
    section_title: Optional[str] = None


@dataclass(frozen=True)
class FrontMatterTemplateConfig:
    key: str
    title: str
    description: str
    field_specs: List[FrontMatterFieldSpec]


def _default_field(key: str, label: str, rows: int = 10) -> FrontMatterFieldSpec:
    return FrontMatterFieldSpec(
        key=key,
        label=label,
        rows=rows,
        help_text="Use blank lines to create new paragraphs. Single line breaks stay within the same paragraph.",
    )


def _about_section_fields(sections) -> List[FrontMatterFieldSpec]:
    specs: List[FrontMatterFieldSpec] = []
    for section in sections or []:
        number = section.number or ""
        display_label = f"{number} {section.title}".strip()
        key_source = number or section.title or "section"
        key = f"section_{slugify(key_source)}" or "section"
        specs.append(
            FrontMatterFieldSpec(
                key=key,
                label=display_label or "Section",
                section_number=number or None,
                section_title=section.title,
                rows=8,
                help_text="Add the narrative for this subsection.",
            )
        )
    return specs


def _build_template_configs() -> Dict[str, FrontMatterTemplateConfig]:
    configs: Dict[str, FrontMatterTemplateConfig] = {}
    for template in FRONT_MATTER_TEMPLATE:
        if template.key == "front_matter_advisory_board":
            fields = [
                _default_field(
                    "body",
                    "Advisory board text",
                    rows=14,
                )
            ]
            description = (
                "Capture the advisory board acknowledgement exactly as it should appear in print."
            )
        elif template.key == "front_matter_authors":
            fields = [
                _default_field(
                    "body",
                    "Author biographies",
                    rows=14,
                )
            ]
            description = "Summarise the authors and their affiliations."
        elif template.key == "front_matter_acknowledgements":
            fields = [
                _default_field(
                    "body",
                    "Acknowledgements text",
                    rows=12,
                )
            ]
            description = "Thank funders, collaborators, and anyone else who supported the project."
        elif template.key == "front_matter_about":
            fields = _about_section_fields(template.sections or [])
            description = "Fill in each subsection so the “About this book” chapter stays structured."
        else:
            fields = [
                _default_field(
                    "body",
                    f"{template.title} text",
                    rows=10,
                )
            ]
            description = "Provide the content for this front matter chapter."

        configs[template.key] = FrontMatterTemplateConfig(
            key=template.key,
            title=template.title,
            description=description,
            field_specs=fields,
        )
    return configs


FRONT_MATTER_TEMPLATE_CONFIGS = _build_template_configs()


def get_front_matter_config(template_key: str) -> Optional[FrontMatterTemplateConfig]:
    return FRONT_MATTER_TEMPLATE_CONFIGS.get(template_key)


def _split_paragraphs(value: str) -> List[str]:
    text = (value or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    parts = [part.strip() for part in text.split("\n\n")]
    paragraphs = [part for part in parts if part]
    return paragraphs or []


def _next_section_position(chapter) -> int:
    max_pos = chapter.sections.aggregate(Max("position"))["position__max"] or 0
    return max_pos + 1


def _ensure_section(chapter, spec: FrontMatterFieldSpec) -> Optional[SynopsisOutlineSection]:
    if not spec.section_number:
        return None
    section = chapter.sections.filter(number_label=spec.section_number).first()
    if section:
        return section
    return SynopsisOutlineSection.objects.create(
        chapter=chapter,
        title=spec.section_title or "",
        number_label=spec.section_number,
        position=_next_section_position(chapter),
    )


def save_front_matter_content(chapter, config: FrontMatterTemplateConfig, cleaned_data: Dict[str, str]) -> None:
    chapter.blocks.all().delete()
    sections_cache: Dict[str, SynopsisOutlineSection] = {}
    position = 1
    preview_segments: List[str] = []

    for spec in config.field_specs:
        value = (cleaned_data.get(spec.key) or "").strip()
        if not value:
            continue
        paragraphs = _split_paragraphs(value)
        if not paragraphs:
            continue

        section = None
        if spec.section_number:
            section = sections_cache.get(spec.section_number)
            if not section:
                section = _ensure_section(chapter, spec)
                if section:
                    sections_cache[spec.section_number] = section

        for paragraph in paragraphs:
            if len(preview_segments) < 3:
                preview_segments.append(paragraph.strip())
            SynopsisOutlineBlock.objects.create(
                chapter=chapter,
                section=section,
                block_type=SynopsisOutlineBlock.TYPE_PARAGRAPH,
                text=paragraph,
                position=position,
                metadata={"front_matter_field": spec.key},
            )
            position += 1

    preview_text = "\n\n".join(part for part in preview_segments if part).strip()
    if preview_text and chapter.summary != preview_text:
        chapter.summary = preview_text
        chapter.save(update_fields=["summary", "updated_at"])


def _ordered_blocks(blocks: Iterable[SynopsisOutlineBlock]) -> Dict[str, List[SynopsisOutlineBlock]]:
    grouped: Dict[str, List[SynopsisOutlineBlock]] = {}
    for block in blocks:
        metadata = block.metadata or {}
        key = metadata.get("front_matter_field")
        if key:
            grouped.setdefault(key, []).append(block)
    return grouped


def get_front_matter_initial_values(chapter, config: FrontMatterTemplateConfig) -> Dict[str, str]:
    values: Dict[str, str] = {spec.key: "" for spec in config.field_specs}
    all_blocks = list(chapter.blocks.order_by("position", "id"))
    grouped = _ordered_blocks(all_blocks)
    section_blocks: Dict[int, List[SynopsisOutlineBlock]] = {}
    for block in all_blocks:
        if block.section_id:
            section_blocks.setdefault(block.section_id, []).append(block)
    sections_by_number = {
        section.number_label: section.id for section in chapter.sections.all() if section.number_label
    }
    loose_blocks = [block for block in all_blocks if not block.section_id]

    for spec in config.field_specs:
        paragraphs: List[str] = []
        if grouped.get(spec.key):
            paragraphs = [blk.text for blk in grouped[spec.key]]
        elif spec.section_number and spec.section_number in sections_by_number:
            paragraphs = [
                blk.text
                for blk in section_blocks.get(sections_by_number[spec.section_number], [])
            ]
        elif spec.key == "body":
            paragraphs = [blk.text for blk in loose_blocks]
        values[spec.key] = "\n\n".join(part.strip() for part in paragraphs if part.strip())
    return values
