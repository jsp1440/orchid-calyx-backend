from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True)
class HomepageImageCandidate:
    image_id: str
    url: str
    license: str | None
    attribution: str | None
    approved_source: bool
    is_herbarium_or_document_plate: bool = False

    @property
    def eligible(self) -> bool:
        return bool(
            self.approved_source
            and self.license
            and self.attribution
            and not self.is_herbarium_or_document_plate
        )


@dataclass(frozen=True)
class HomepageFeatureCandidate:
    taxon_id: str
    accepted_name: str
    content_score: float
    freshness_at: datetime | None
    provenance: tuple[str, ...]
    images: tuple[HomepageImageCandidate, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.content_score <= 1:
            raise ValueError("CONTENT_SCORE_OUT_OF_RANGE")


def select_homepage_feature(
    candidates: tuple[HomepageFeatureCandidate, ...],
) -> dict[str, object]:
    """Select a feature candidate using server-owned deterministic governance."""

    eligible = [candidate for candidate in candidates if any(image.eligible for image in candidate.images)]
    if not eligible:
        return {
            "availability": "unavailable",
            "data": None,
            "limitations": ["No candidate had an eligible, licensed, attributed image."],
            "selected_at": datetime.now(UTC).isoformat(),
        }

    eligible.sort(
        key=lambda candidate: (
            -candidate.content_score,
            -(candidate.freshness_at.timestamp() if candidate.freshness_at else 0),
            candidate.accepted_name,
            candidate.taxon_id,
        )
    )
    selected = eligible[0]
    image = next(image for image in selected.images if image.eligible)
    return {
        "availability": "available",
        "data": {
            "taxon_id": selected.taxon_id,
            "accepted_name": selected.accepted_name,
            "image": {
                "image_id": image.image_id,
                "url": image.url,
                "license": image.license,
                "attribution": image.attribution,
            },
        },
        "provenance": list(selected.provenance),
        "freshness_at": selected.freshness_at.isoformat() if selected.freshness_at else None,
        "selection_score": selected.content_score,
        "client_scoring_allowed": False,
    }
