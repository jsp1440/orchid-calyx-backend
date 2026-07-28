"""Default article presets for the Calyx Journalism MVP.

The FCOS (Focus on Conservation Orchid Survey) preset is the default
800–1,500 word global orchid-conservation survey.
"""
from __future__ import annotations

from .schemas import ArticleBrief, PublicationMeta


# ---------------------------------------------------------------------------
# FCOS — default conservation survey preset
# ---------------------------------------------------------------------------

FCOS_PUBLICATION = PublicationMeta(
    publication_id="fcos-global-orchid-conservation",
    publication_name="Orchid Continuum — Conservation Report",
    theme="global_orchid_conservation",
    description=(
        "The FCOS (Focus on Conservation Orchid Survey) is a recurring "
        "same-day report covering global orchid conservation status, "
        "habitat threats, and verified project activity."
    ),
    language="en",
)

FCOS_BRIEF = ArticleBrief(
    title="Global Orchid Conservation: Status, Threats, and Active Projects",
    focus=(
        "Survey the current state of global orchid conservation, covering "
        "habitat loss, climate-driven range shifts, invasive species pressure, "
        "and the projects that address these threats. Ground all claims in "
        "verified evidence from the Orchid Continuum corpus. "
        "Do not fabricate project counts, citations, confidence scores, or "
        "conservation status."
    ),
    target_word_count_min=800,
    target_word_count_max=1500,
    scope_hints=[
        "global",
        "conservation",
        "habitat",
        "climate",
        "invasive species",
        "CITES",
        "IUCN Red List",
    ],
    tags=["conservation", "orchid", "global-survey", "fcos"],
)


def fcos_preset() -> dict[str, object]:
    """Return the FCOS preset as a plain dict for API serialisation."""
    return {
        "preset_id": "fcos",
        "label": "FCOS global orchid-conservation survey (800–1,500 words)",
        "publication": FCOS_PUBLICATION.model_dump(),
        "brief": FCOS_BRIEF.model_dump(),
    }


# ---------------------------------------------------------------------------
# Preset registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, dict[str, object]] = {
    "fcos": fcos_preset(),
}


def list_presets() -> list[dict[str, object]]:
    return list(_REGISTRY.values())


def get_preset(preset_id: str) -> dict[str, object] | None:
    return _REGISTRY.get(preset_id)
