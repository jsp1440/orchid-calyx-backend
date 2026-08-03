from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

HOMEPAGE_SECTION_IDS = (
    "mission",
    "featured_genus",
    "featured_species",
    "evolution",
    "relationships",
    "species",
    "conservation",
    "education",
    "research",
    "current_activity",
)


@dataclass(frozen=True)
class HomepageSection:
    section_id: str
    availability: str
    data: dict[str, Any] | None
    evidence: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    freshness_at: datetime | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.section_id not in HOMEPAGE_SECTION_IDS:
            raise ValueError("UNKNOWN_HOMEPAGE_SECTION")
        if self.availability not in {"available", "degraded", "unavailable"}:
            raise ValueError("INVALID_AVAILABILITY")
        if self.availability == "available" and self.data is None:
            raise ValueError("AVAILABLE_SECTION_REQUIRES_DATA")
        if self.availability == "unavailable" and self.data is not None:
            raise ValueError("UNAVAILABLE_SECTION_CANNOT_HAVE_DATA")

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.section_id,
            "availability": self.availability,
            "data": self.data,
            "evidence": list(self.evidence),
            "provenance": list(self.provenance),
            "freshness_at": self.freshness_at.isoformat() if self.freshness_at else None,
            "message": self.message,
        }


def build_homepage_document(
    sections: tuple[HomepageSection, ...],
    *,
    contract_version: str = "oc-parallel-v1",
) -> dict[str, Any]:
    supplied = {section.section_id: section for section in sections}
    normalized: list[HomepageSection] = []
    for section_id in HOMEPAGE_SECTION_IDS:
        normalized.append(
            supplied.get(
                section_id,
                HomepageSection(
                    section_id=section_id,
                    availability="unavailable",
                    data=None,
                    freshness_at=datetime.now(UTC),
                    message="Canonical source integration is unavailable for this section.",
                ),
            )
        )
    return {
        "contract_version": contract_version,
        "generated_at": datetime.now(UTC).isoformat(),
        "title": "Orchid Continuum",
        "sections": [section.as_dict() for section in normalized],
        "governance": {
            "real_approved_imagery_only": True,
            "attribution_required": True,
            "provenance_required": True,
            "uncertainty_required": True,
            "client_scoring_allowed": False,
        },
    }
