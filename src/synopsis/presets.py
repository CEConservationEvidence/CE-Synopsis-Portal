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
        {"title": "Advisory Board", "subheadings": []},
        {"title": "About the authors", "subheadings": []},
        {"title": "Acknowledgements", "subheadings": []},
        {"title": "1. About this book", "subheadings": []},
        {"title": "2. Threat: Residential and commercial development", "subheadings": []},
        {"title": "3. Threat: Aquaculture & agriculture", "subheadings": []},
        {"title": "4. Threat: Energy production and mining", "subheadings": []},
        {"title": "5. Threat: Transportation and service corridors", "subheadings": []},
        {"title": "6. Threat: Biological resource use", "subheadings": []},
        {"title": "7. Threat: Human intrusions and disturbances", "subheadings": []},
        {"title": "8. Invasive alien and other problematic species", "subheadings": []},
        {"title": "9. Threat: Pollution", "subheadings": []},
        {"title": "10. Threat: Climate change and severe weather", "subheadings": []},
        {"title": "11. Habitat protection", "subheadings": []},
        {"title": "12. Habitat restoration and creation", "subheadings": []},
        {"title": "13. Species management", "subheadings": []},
        {"title": "14. Education and awareness", "subheadings": []},
        {"title": "References", "subheadings": []},
        {"title": "Appendix 1: English language journals (and years) searched", "subheadings": []},
        {"title": "Appendix 2: Non-English language journals (and years) searched", "subheadings": []},
        {"title": "Appendix 3: Reports (and years) searched", "subheadings": []},
        {"title": "Appendix 4: Literature reviewed for the Coral Conservation Synopsis", "subheadings": []},
        {"title": "Index", "subheadings": []},
    ],
)


PRESETS = {preset.key: preset for preset in [STANDARD_CE_TOC]}
