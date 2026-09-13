"""Governed, read-only Atlas product-path contract (OC-ATLAS-001, #1254).

This module carries navigation readiness only.  It neither connects to the live
Atlas database nor publishes taxonomy, tours, occurrences, or locality data.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Any


class AtlasEntryPoint(str, Enum):
    GENUS = "genus"
    SPECIES = "species"


class AtlasTaxonReviewState(str, Enum):
    REVIEWED = "reviewed"
    PROVISIONAL = "provisional"
    UNREVIEWED = "unreviewed"


class AtlasOccurrenceState(str, Enum):
    AVAILABLE = "available"
    ABSENT = "absent"
    UNAVAILABLE = "unavailable"


class AtlasTourContentState(str, Enum):
    AVAILABLE = "available"
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    UNAVAILABLE = "unavailable"


class AtlasEvidenceState(str, Enum):
    PRESENT = "present"
    UNKNOWN = "unknown"
    ABSENT = "absent"
    WITHHELD = "withheld"
    CONTRADICTORY = "contradictory"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class CanonicalTaxonBinding:
    canonical_taxon_id: str
    scientific_name: str
    rank: AtlasEntryPoint
    source: str
    review_state: AtlasTaxonReviewState

    def __post_init__(self) -> None:
        for field_name in ("canonical_taxon_id", "scientific_name", "source"):
            value = str(getattr(self, field_name)).strip()
            if not value:
                raise ValueError(f"{field_name} must not be empty")
            object.__setattr__(self, field_name, value)

    def to_dict(self) -> dict[str, str]:
        return {
            "canonical_taxon_id": self.canonical_taxon_id,
            "scientific_name": self.scientific_name,
            "rank": self.rank.value,
            "source": self.source,
            "review_state": self.review_state.value,
        }


def select_canonical_taxon_binding(
    candidates: Iterable[CanonicalTaxonBinding],
) -> CanonicalTaxonBinding | None:
    """Select deterministically, with reviewed identity always outranking provisional."""

    precedence = {
        AtlasTaxonReviewState.REVIEWED: 0,
        AtlasTaxonReviewState.PROVISIONAL: 1,
        AtlasTaxonReviewState.UNREVIEWED: 2,
    }
    ordered = sorted(
        candidates,
        key=lambda item: (
            precedence[item.review_state],
            item.canonical_taxon_id.casefold(),
            item.source.casefold(),
        ),
    )
    return ordered[0] if ordered else None


@dataclass(frozen=True, slots=True)
class AtlasProductPath:
    entry_point: AtlasEntryPoint
    taxon_binding: CanonicalTaxonBinding | None
    occurrence_state: AtlasOccurrenceState
    occurrence_count: int | None
    tour_content_state: AtlasTourContentState
    tour_content: str | None
    evidence_state: AtlasEvidenceState
    human_review_required: bool

    def __post_init__(self) -> None:
        if self.taxon_binding is not None and self.taxon_binding.rank is not self.entry_point:
            raise ValueError("taxon binding rank must match the Atlas entry point")
        if self.occurrence_state is AtlasOccurrenceState.AVAILABLE:
            if self.occurrence_count is None or self.occurrence_count < 1:
                raise ValueError("available occurrence context requires a positive count")
        elif self.occurrence_count is not None:
            raise ValueError("absent or unavailable occurrence context has no count")
        if self.tour_content_state is AtlasTourContentState.AVAILABLE:
            if self.human_review_required:
                raise ValueError("unreviewed tour content cannot be available")
            if not (self.tour_content or "").strip():
                raise ValueError("available tour content must not be empty")
        elif self.tour_content is not None:
            raise ValueError("draft, pending, or unavailable tour content must be withheld")
        if self.taxon_binding is None and self.evidence_state is AtlasEvidenceState.PRESENT:
            raise ValueError("present evidence requires a canonical taxon binding")

    @property
    def species_present(self) -> bool | None:
        """Return presence only from explicit occurrence evidence."""

        if self.occurrence_state is AtlasOccurrenceState.UNAVAILABLE:
            return None
        return self.occurrence_state is AtlasOccurrenceState.AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        """Return the public contract; locality and unpublished draft fields do not exist."""

        return {
            "schema_version": "atlas-product-path-v1",
            "entry_point": self.entry_point.value,
            "taxon_binding": (
                self.taxon_binding.to_dict() if self.taxon_binding is not None else None
            ),
            "occurrence_context": {
                "state": self.occurrence_state.value,
                "count": self.occurrence_count,
                "species_present": self.species_present,
            },
            "guided_tour": {
                "state": self.tour_content_state.value,
                "content": self.tour_content,
            },
            "evidence_state": self.evidence_state.value,
            "human_review_required": self.human_review_required,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
        }


def build_unavailable_atlas_snapshot(entry_point: AtlasEntryPoint) -> AtlasProductPath:
    return AtlasProductPath(
        entry_point=entry_point,
        taxon_binding=None,
        occurrence_state=AtlasOccurrenceState.UNAVAILABLE,
        occurrence_count=None,
        tour_content_state=AtlasTourContentState.UNAVAILABLE,
        tour_content=None,
        evidence_state=AtlasEvidenceState.UNAVAILABLE,
        human_review_required=True,
    )


class AtlasNavigationGateway:
    """Read-through boundary that fails closed when Atlas persistence is absent."""

    def __init__(
        self,
        loader: Callable[[AtlasEntryPoint], AtlasProductPath | None] | None = None,
    ) -> None:
        self._loader = loader

    def resolve(self, entry_point: AtlasEntryPoint) -> AtlasProductPath:
        if self._loader is None:
            return build_unavailable_atlas_snapshot(entry_point)
        result = self._loader(entry_point)
        if result is None:
            return build_unavailable_atlas_snapshot(entry_point)
        if result.entry_point is not entry_point:
            raise ValueError("Atlas loader returned a mismatched entry point")
        return result
