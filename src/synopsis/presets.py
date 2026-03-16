from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class SynopsisPreset:
    key: str
    label: str
    description: Optional[str]
    chapters: List[dict]


STANDARD_CE_TOC = SynopsisPreset(
    key="standard_ce_toc",
    label="Standard CE synopsis (full ToC, chapters only)",
    description="Top-level chapters from the published CE synopsis format; add subheadings/interventions yourself.",
    chapters=[
        {"title": "Advisory Board", "chapter_type": "text", "subheadings": []},
        {"title": "About the authors", "chapter_type": "text", "subheadings": []},
        {"title": "Acknowledgements", "chapter_type": "text", "subheadings": []},
        {"title": "1. About this book", "chapter_type": "text", "subheadings": []},
        {
            "title": "2. Threat: Residential and commercial development",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {
            "title": "3. Threat: Aquaculture & agriculture",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {
            "title": "4. Threat: Energy production and mining",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {
            "title": "5. Threat: Transportation and service corridors",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {
            "title": "6. Threat: Biological resource use",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {
            "title": "7. Threat: Human intrusions and disturbances",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {
            "title": "8. Invasive alien and other problematic species",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {"title": "9. Threat: Pollution", "chapter_type": "evidence", "subheadings": []},
        {
            "title": "10. Threat: Climate change and severe weather",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {"title": "11. Habitat protection", "chapter_type": "evidence", "subheadings": []},
        {
            "title": "12. Habitat restoration and creation",
            "chapter_type": "evidence",
            "subheadings": [],
        },
        {"title": "13. Species management", "chapter_type": "evidence", "subheadings": []},
        {"title": "14. Education and awareness", "chapter_type": "evidence", "subheadings": []},
        {"title": "References", "chapter_type": "appendix", "subheadings": []},
        {
            "title": "Appendix 1: English language journals (and years) searched",
            "chapter_type": "appendix",
            "subheadings": [],
        },
        {
            "title": "Appendix 2: Non-English language journals (and years) searched",
            "chapter_type": "appendix",
            "subheadings": [],
        },
        {
            "title": "Appendix 3: Reports (and years) searched",
            "chapter_type": "appendix",
            "subheadings": [],
        },
        {
            "title": "Appendix 4: Literature reviewed for the Coral Conservation Synopsis",
            "chapter_type": "appendix",
            "subheadings": [],
        },
        {"title": "Index", "chapter_type": "appendix", "subheadings": []},
    ],
)


PRESETS = {preset.key: preset for preset in [STANDARD_CE_TOC]}
