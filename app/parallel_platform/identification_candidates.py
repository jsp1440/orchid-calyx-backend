from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.parallel_platform.identification_observations import (
    OrchidObservation,
    choose_next_best_observation,
)


@dataclass(frozen=True)
class IdentificationCandidateRecord:
    taxon_id: str
    accepted_name: str
    features: dict[str, Any]
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True)
class RankedIdentificationCandidate:
    taxon_id: str
    accepted_name: str
    fit_score: float
    supporting_characters: tuple[str, ...]
    conflicting_characters: tuple[str, ...]
    missing_observations: tuple[str, ...]
    provenance: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "taxon_id": self.taxon_id,
            "accepted_name": self.accepted_name,
            "fit_score": self.fit_score,
            "supporting_characters": list(self.supporting_characters),
            "conflicting_characters": list(self.conflicting_characters),
            "missing_observations": list(self.missing_observations),
            "provenance": list(self.provenance),
            "verified_identity": False,
        }


def rank_identification_candidates(
    observation: OrchidObservation,
    candidates: tuple[IdentificationCandidateRecord, ...],
    *,
    limit: int = 20,
) -> dict[str, object]:
    if not 1 <= limit <= 100:
        raise ValueError("LIMIT_OUT_OF_RANGE")

    observed = observation.as_feature_map()
    ranked: list[RankedIdentificationCandidate] = []
    for candidate in candidates:
        supporting = tuple(
            character
            for character, value in observed.items()
            if character in candidate.features and candidate.features[character] == value
        )
        conflicting = tuple(
            character
            for character, value in observed.items()
            if character in candidate.features and candidate.features[character] != value
        )
        compared = len(supporting) + len(conflicting)
        fit_score = len(supporting) / compared if compared else 0.0
        missing = tuple(
            character for character in observation.missing_characters() if character in candidate.features
        )
        ranked.append(
            RankedIdentificationCandidate(
                taxon_id=candidate.taxon_id,
                accepted_name=candidate.accepted_name,
                fit_score=round(fit_score, 6),
                supporting_characters=supporting,
                conflicting_characters=conflicting,
                missing_observations=missing,
                provenance=candidate.provenance,
            )
        )

    ranked.sort(
        key=lambda item: (
            -item.fit_score,
            len(item.conflicting_characters),
            -len(item.supporting_characters),
            item.accepted_name,
            item.taxon_id,
        )
    )
    selected = tuple(ranked[:limit])
    next_character = choose_next_best_observation(
        observation,
        tuple(candidate.features for candidate in candidates),
    )
    top_scores = [candidate.fit_score for candidate in selected[:2]]
    state = "candidate_suggestions"
    if not selected:
        state = "observation_incomplete"
    elif len(top_scores) == 2 and top_scores[0] == top_scores[1]:
        state = "ambiguous"
    return {
        "state": state,
        "candidates": [candidate.as_dict() for candidate in selected],
        "next_best_observation": next_character,
        "verified_identity": None,
        "publication_authority": False,
    }
