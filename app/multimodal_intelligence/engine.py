from __future__ import annotations

from collections.abc import Iterable, Mapping

from .contracts import (
    CharacterContribution,
    CharacterDefinition,
    CharacterObservation,
    ImageAnalysisResult,
    MatrixCandidate,
    MatrixProfile,
)


def rank_matrix_candidates(
    *,
    definitions: Mapping[str, CharacterDefinition],
    observations: Iterable[CharacterObservation],
    profiles: Iterable[MatrixProfile],
) -> tuple[MatrixCandidate, ...]:
    observation_list = tuple(observations)
    for definition in definitions.values():
        definition.validate()
    for observation in observation_list:
        observation.validate()
        definition = definitions.get(observation.character_id)
        if definition is None:
            raise ValueError("UNKNOWN_CHARACTER")
        if observation.state is not None and observation.state not in definition.allowed_states:
            raise ValueError("UNKNOWN_CHARACTER_STATE")

    candidates: list[MatrixCandidate] = []
    for profile in profiles:
        profile.validate()
        contributions: list[CharacterContribution] = []
        support = 0
        contradictions = 0
        unknown = 0
        score = 0.0
        total_weight = 0.0
        for observation in observation_list:
            definition = definitions[observation.character_id]
            weight = definition.weight * observation.confidence
            expected = profile.states.get(observation.character_id)
            if observation.state is None or not expected:
                outcome = "unknown"
                weighted_score = 0.0
                unknown += 1
            elif observation.state in expected:
                outcome = "support"
                weighted_score = weight
                score += weighted_score
                support += 1
                total_weight += weight
            else:
                outcome = "contradiction"
                weighted_score = -weight
                score += weighted_score
                contradictions += 1
                total_weight += weight
            contributions.append(
                CharacterContribution(
                    character_id=observation.character_id,
                    observed_state=observation.state,
                    expected_states=tuple(sorted(expected or ())),
                    outcome=outcome,
                    weighted_score=round(weighted_score, 6),
                )
            )
        normalized = 0.0 if total_weight == 0 else (score + total_weight) / (2 * total_weight)
        candidates.append(
            MatrixCandidate(
                taxon_id=profile.taxon_id,
                accepted_name=profile.accepted_name,
                score=round(normalized, 6),
                support_count=support,
                contradiction_count=contradictions,
                unknown_count=unknown,
                contributions=tuple(contributions),
            )
        )
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (
                -candidate.score,
                candidate.contradiction_count,
                -candidate.support_count,
                candidate.accepted_name,
            ),
        )
    )


def matrix_observations_from_vision(result: ImageAnalysisResult) -> tuple[CharacterObservation, ...]:
    result.validate()
    return tuple(
        CharacterObservation(
            character_id=observation.character_id,
            state=observation.state,
            confidence=min(observation.confidence, 0.95),
            provenance=(
                *observation.provenance,
                f"image:{result.image_id}",
                f"model:{result.model.provider}/{result.model.model_name}@{result.model.model_version}",
                f"inference:{result.model.inference_id}",
            ),
        )
        for observation in result.character_observations
    )
