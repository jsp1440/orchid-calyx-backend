from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

OBSERVATION_CHARACTERS = (
    "habit",
    "leaf_shape",
    "leaf_texture",
    "pseudobulb_or_stem",
    "inflorescence_type",
    "flower_shape",
    "lip_structure",
    "column_structure",
    "spur",
    "color_markings",
    "fragrance",
    "flowering_season",
    "geography",
    "elevation",
    "habitat",
    "plant_size",
)

OBSERVATION_STATES = {"observed", "not_observed", "uncertain", "not_applicable"}


@dataclass(frozen=True)
class CharacterObservation:
    character: str
    state: str
    value: Any = None
    confidence: float | None = None
    source_media_ids: tuple[str, ...] = ()
    notes: str | None = None

    def __post_init__(self) -> None:
        if self.character not in OBSERVATION_CHARACTERS:
            raise ValueError("UNKNOWN_IDENTIFICATION_CHARACTER")
        if self.state not in OBSERVATION_STATES:
            raise ValueError("INVALID_OBSERVATION_STATE")
        if self.state != "observed" and self.value is not None:
            raise ValueError("NON_OBSERVED_CHARACTER_CANNOT_HAVE_VALUE")
        if self.confidence is not None and not 0 <= self.confidence <= 1:
            raise ValueError("CONFIDENCE_OUT_OF_RANGE")


@dataclass(frozen=True)
class OrchidObservation:
    observation_id: str
    characters: tuple[CharacterObservation, ...]
    submitted_taxon_hint: str | None = None
    provenance: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def as_feature_map(self) -> dict[str, Any]:
        return {
            item.character: item.value
            for item in self.characters
            if item.state == "observed"
        }

    def missing_characters(self) -> tuple[str, ...]:
        observed = {item.character for item in self.characters if item.state == "observed"}
        return tuple(character for character in OBSERVATION_CHARACTERS if character not in observed)


def choose_next_best_observation(
    observation: OrchidObservation,
    candidate_feature_maps: tuple[dict[str, Any], ...],
) -> str | None:
    """Choose the missing character with the greatest candidate-value diversity."""

    missing = observation.missing_characters()
    best_character: str | None = None
    best_diversity = 0
    for character in missing:
        values = {
            features[character]
            for features in candidate_feature_maps
            if character in features and features[character] is not None
        }
        if len(values) > best_diversity:
            best_character = character
            best_diversity = len(values)
    return best_character
