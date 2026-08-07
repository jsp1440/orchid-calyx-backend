"""Governed, explainable character-matrix identification engine.

This module ranks supplied candidate taxa. It does not assert a taxonomic
identification and does not mutate canonical taxonomy or collection records.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Literal

Certainty = Literal["certain", "probable", "uncertain", "unknown"]

_CERTAINTY_FACTOR: dict[Certainty, float] = {
    "certain": 1.0,
    "probable": 0.75,
    "uncertain": 0.4,
    "unknown": 0.0,
}


@dataclass(frozen=True)
class Observation:
    character: str
    value: Any
    certainty: Certainty = "certain"
    weight: float = 1.0


@dataclass(frozen=True)
class Candidate:
    taxon_id: str
    scientific_name: str
    states: dict[str, Any]
    provenance: dict[str, Any] | None = None


@dataclass(frozen=True)
class CharacterExplanation:
    character: str
    observation: Any
    candidate_state: Any
    certainty: Certainty
    effective_weight: float
    similarity: float | None
    contribution: float
    status: str


@dataclass(frozen=True)
class CandidateResult:
    taxon_id: str
    scientific_name: str
    score: float
    coverage: float
    compared_weight: float
    possible_weight: float
    explanations: list[dict[str, Any]]
    provenance: dict[str, Any] | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_set(value: Any) -> set[str]:
    if isinstance(value, (list, tuple, set)):
        return {str(item).strip().casefold() for item in value if str(item).strip()}
    text = str(value).strip()
    return {text.casefold()} if text else set()


def _numeric_similarity(observed: Any, candidate_state: Any) -> float | None:
    if not isinstance(observed, (int, float)):
        return None
    if isinstance(candidate_state, (int, float)):
        if candidate_state == observed:
            return 1.0
        scale = max(abs(float(observed)), abs(float(candidate_state)), 1.0)
        return max(0.0, 1.0 - abs(float(observed) - float(candidate_state)) / scale)
    if (
        isinstance(candidate_state, dict)
        and isinstance(candidate_state.get("min"), (int, float))
        and isinstance(candidate_state.get("max"), (int, float))
    ):
        lower = float(candidate_state["min"])
        upper = float(candidate_state["max"])
        value = float(observed)
        if lower <= value <= upper:
            return 1.0
        span = max(upper - lower, 1.0)
        distance = lower - value if value < lower else value - upper
        return max(0.0, 1.0 - distance / span)
    return None


def state_similarity(observed: Any, candidate_state: Any) -> float:
    """Return a deterministic similarity in the closed interval [0, 1]."""
    numeric = _numeric_similarity(observed, candidate_state)
    if numeric is not None:
        return numeric
    observed_values = _as_set(observed)
    candidate_values = _as_set(candidate_state)
    if not observed_values or not candidate_values:
        return 0.0
    intersection = observed_values & candidate_values
    union = observed_values | candidate_values
    return len(intersection) / len(union)


def rank_candidates(
    observations: list[Observation],
    candidates: list[Candidate],
    *,
    limit: int = 20,
) -> dict[str, Any]:
    """Rank candidates while preserving unknowns, uncertainty, and explanations."""
    if limit < 1 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if not candidates:
        return {
            "candidates": [],
            "observation_count": len(observations),
            "compared_character_count": 0,
            "disclaimer": "No candidates were supplied; no identification was attempted.",
        }

    active = [item for item in observations if _CERTAINTY_FACTOR[item.certainty] > 0]
    possible_weight = sum(
        max(item.weight, 0.0) * _CERTAINTY_FACTOR[item.certainty] for item in active
    )
    results: list[CandidateResult] = []

    for candidate in candidates:
        compared_weight = 0.0
        weighted_score = 0.0
        explanations: list[dict[str, Any]] = []
        for observation in observations:
            factor = _CERTAINTY_FACTOR[observation.certainty]
            effective_weight = max(observation.weight, 0.0) * factor
            candidate_state = candidate.states.get(observation.character)
            if factor == 0:
                explanation = CharacterExplanation(
                    character=observation.character,
                    observation=observation.value,
                    candidate_state=candidate_state,
                    certainty=observation.certainty,
                    effective_weight=0.0,
                    similarity=None,
                    contribution=0.0,
                    status="ignored_unknown_observation",
                )
            elif candidate_state is None:
                explanation = CharacterExplanation(
                    character=observation.character,
                    observation=observation.value,
                    candidate_state=None,
                    certainty=observation.certainty,
                    effective_weight=effective_weight,
                    similarity=None,
                    contribution=0.0,
                    status="candidate_state_missing",
                )
            else:
                similarity = state_similarity(observation.value, candidate_state)
                contribution = effective_weight * similarity
                compared_weight += effective_weight
                weighted_score += contribution
                explanation = CharacterExplanation(
                    character=observation.character,
                    observation=observation.value,
                    candidate_state=candidate_state,
                    certainty=observation.certainty,
                    effective_weight=round(effective_weight, 6),
                    similarity=round(similarity, 6),
                    contribution=round(contribution, 6),
                    status="matched"
                    if similarity == 1
                    else "partial"
                    if similarity > 0
                    else "conflict",
                )
            explanations.append(asdict(explanation))

        score = weighted_score / compared_weight if compared_weight else 0.0
        coverage = compared_weight / possible_weight if possible_weight else 0.0
        results.append(
            CandidateResult(
                taxon_id=candidate.taxon_id,
                scientific_name=candidate.scientific_name,
                score=round(score, 6),
                coverage=round(coverage, 6),
                compared_weight=round(compared_weight, 6),
                possible_weight=round(possible_weight, 6),
                explanations=explanations,
                provenance=candidate.provenance,
            )
        )

    ordered = sorted(
        results,
        key=lambda item: (
            -item.score,
            -item.coverage,
            item.scientific_name.casefold(),
            item.taxon_id,
        ),
    )[:limit]
    return {
        "candidates": [item.as_dict() for item in ordered],
        "observation_count": len(observations),
        "compared_character_count": len(active),
        "disclaimer": (
            "Scores are candidate-ranking evidence, not a taxonomic determination. "
            "Missing data are not treated as biological absence."
        ),
    }
