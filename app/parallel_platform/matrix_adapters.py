from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

MATRIX_DIMENSIONS = (
    "taxonomy",
    "morphology",
    "ecology",
    "geography",
    "phenology",
    "pollinators",
    "mycorrhizae",
    "conservation",
    "cultivation",
    "literature",
    "graph_topology",
)


@dataclass(frozen=True)
class DimensionEvidence:
    dimension: str
    availability: str
    score: float | None = None
    confidence: float | None = None
    evidence: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()
    freshness_at: datetime | None = None
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.dimension not in MATRIX_DIMENSIONS:
            raise ValueError("UNKNOWN_MATRIX_DIMENSION")
        if self.availability not in {"available", "degraded", "unavailable"}:
            raise ValueError("INVALID_AVAILABILITY")
        if self.availability == "unavailable" and self.score is not None:
            raise ValueError("UNAVAILABLE_DIMENSION_CANNOT_HAVE_SCORE")
        if self.score is not None and not 0 <= self.score <= 1:
            raise ValueError("SCORE_OUT_OF_RANGE")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")

    def as_dict(self) -> dict[str, object]:
        return {
            "dimension": self.dimension,
            "availability": self.availability,
            "score": self.score,
            "confidence": self.confidence,
            "evidence": list(self.evidence),
            "provenance": list(self.provenance),
            "freshness_at": self.freshness_at.isoformat() if self.freshness_at else None,
            "limitations": list(self.limitations),
        }


class MatrixEvidenceAdapter(Protocol):
    dimension: str

    def compare(self, subject_taxon_id: str, object_taxon_id: str) -> DimensionEvidence: ...


@dataclass
class StaticMatrixEvidenceAdapter:
    """Deterministic adapter used for contract tests and bounded fallbacks."""

    dimension: str
    records: dict[tuple[str, str], DimensionEvidence] = field(default_factory=dict)

    def compare(self, subject_taxon_id: str, object_taxon_id: str) -> DimensionEvidence:
        key = (subject_taxon_id, object_taxon_id)
        reverse_key = (object_taxon_id, subject_taxon_id)
        evidence = self.records.get(key) or self.records.get(reverse_key)
        if evidence is not None:
            return evidence
        return DimensionEvidence(
            dimension=self.dimension,
            availability="unavailable",
            freshness_at=datetime.now(UTC),
            limitations=("No canonical evidence was returned by this adapter.",),
        )


def hydrate_pairwise_dimensions(
    subject_taxon_id: str,
    object_taxon_id: str,
    adapters: tuple[MatrixEvidenceAdapter, ...],
) -> dict[str, DimensionEvidence]:
    results = {adapter.dimension: adapter.compare(subject_taxon_id, object_taxon_id) for adapter in adapters}
    for dimension in MATRIX_DIMENSIONS:
        results.setdefault(
            dimension,
            DimensionEvidence(
                dimension=dimension,
                availability="unavailable",
                limitations=("Adapter not configured.",),
            ),
        )
    return results
