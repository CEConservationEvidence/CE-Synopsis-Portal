from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class TemplateSection:
    title: str
    number: Optional[str] = None


@dataclass(frozen=True)
class TemplateChapter:
    key: str
    title: str
    section_type: str
    section_number: Optional[str] = None
    sections: Optional[List[TemplateSection]] = None
    summary: str = ""


FRONT_MATTER_TEMPLATE: List[TemplateChapter] = [
    TemplateChapter(
        key="front_matter_advisory_board",
        title="Advisory Board",
        section_type="front_matter",
        section_number="0",
    ),
    TemplateChapter(
        key="front_matter_authors",
        title="About the authors",
        section_type="front_matter",
        section_number="0.1",
    ),
    TemplateChapter(
        key="front_matter_acknowledgements",
        title="Acknowledgements",
        section_type="front_matter",
        section_number="0.2",
    ),
    TemplateChapter(
        key="front_matter_about",
        title="About this book",
        section_type="front_matter",
        section_number="1",
        sections=[
            TemplateSection("The Conservation Evidence project", "1.1"),
            TemplateSection("The purpose of Conservation Evidence synopses", "1.2"),
            TemplateSection("Who this synopsis is for", "1.3"),
            TemplateSection("Background", "1.4"),
            TemplateSection("Scope", "1.5"),
            TemplateSection("Methods", "1.6"),
            TemplateSection("How you can help to change conservation practice", "1.7"),
            TemplateSection("References", "1.8"),
        ],
    ),
]
