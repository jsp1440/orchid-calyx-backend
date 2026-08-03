from __future__ import annotations

from dataclasses import dataclass

from app.parallel_platform.matrix_adapters import MATRIX_DIMENSIONS, DimensionEvidence


@dataclass(frozen=True)
class MatrixNeighborCandidate:
    taxon_id: str
    accepted_name: str
    dimensions: dict[str, DimensionEvidence]


@dataclass(frozen=True)
class RankedMatrixNeighbor:
    taxon_id: str
    accepted_name: str
    score: float
    evidence_coverage: float
    available_dimensions: tuple[str, ...]
    unavailable_dimensions: tuple[str, ...]
    explanation: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "taxon_id": self.taxon_id,
            "accepted_name": self.accepted_name,
            "score": self.score,
            "evidence_coverage": self.evidence_coverage,
            "available_dimensions": list(self.available_dimensions),
            "unavailable_dimensions": list(self.unavailable_dimensions),
            "explanation": list(self.explanation),
            "verified_relationship": False,
        }


def rank_matrix_neighbors(
    candidates: tuple[MatrixNeighborCandidate, ...],
    *,
    weights: dict[str, float] | None = None,
    limit: int = 20,
) -> tuple[RankedMatrixNeighbor, ...]:
    """Rank read-only candidate neighbors without treating missing evidence as zero."""

    if not 1 <= limit <= 100:
        raise ValueError("LIMIT_OUT_OF_RANGE")
    normalized_weights = {dimension: 1.0 for dimension in MATRIX_DIMENSIONS}
    if weights:
        for dimension, weight in weights.items():
            if dimension not in MATRIX_DIMENSIONS:
                raise ValueError("UNKNOWN_MATRIX_DIMENSION")
            if weight < 0:
                raise ValueError("NEGATIVE_DIMENSION_WEIGHT")
            normalized_weights[dimension] = weight

    ranked: list[RankedMatrixNeighbor] = []
    for candidate in candidates:
        available = tuple(
            dimension
            for dimension in MATRIX_DIMENSIONS
            if (evidence := candidate.dimensions.get(dimension)) is not None
            and evidence.availability != "unavailable"
            and evidence.score is not None
        )
        unavailable = tuple(dimension for dimension in MATRIX_DIMENSIONS if dimension not in available)
        denominator = sum(normalized_weights[dimension] for dimension in available)
        score = (
            sum(
                candidate.dimensions[dimension].score * normalized_weights[dimension]
                for dimension in available
                if candidate.dimensions[dimension].score is not None
            )
            / denominator
            if denominator > 0
            else 0.0
        )
        strongest = sorted(
            available,
            key=lambda dimension: candidate.dimensions[dimension].score or 0.0,
            reverse=True,
        )[:3]
        explanation = tuple(
            f"{dimension}:{candidate.dimensions[dimension].score:.3f}"
            for dimension in strongest
            if candidate.dimensions[dimension].score is not None
        )
        ranked.append(
            RankedMatrixNeighbor(
                taxon_id=candidate.taxon_id,
                accepted_name=candidate.accepted_name,
                score=round(score, 6),
                evidence_coverage=round(len(available) / len(MATRIX_DIMENSIONS), 6),
                available_dimensions=available,
                unavailable_dimensions=unavailable,
                explanation=explanation,
            )
        )

    ranked.sort(key=lambda item: (-item.score, -item.evidence_coverage, item.accepted_name, item.taxon_id))
    return tuple(ranked[:limit])
