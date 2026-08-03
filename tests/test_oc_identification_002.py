from app.parallel_platform.identification_observations import (
    CharacterObservation,
    OrchidObservation,
    choose_next_best_observation,
)


def test_non_observed_character_cannot_carry_a_value():
    try:
        CharacterObservation(character="fragrance", state="uncertain", value="night")
    except ValueError as exc:
        assert str(exc) == "NON_OBSERVED_CHARACTER_CANNOT_HAVE_VALUE"
    else:
        raise AssertionError("invalid uncertain value was accepted")


def test_feature_map_contains_only_observed_characters():
    observation = OrchidObservation(
        observation_id="obs:1",
        characters=(
            CharacterObservation(character="flower_shape", state="observed", value="star-shaped"),
            CharacterObservation(character="fragrance", state="not_observed"),
        ),
    )
    assert observation.as_feature_map() == {"flower_shape": "star-shaped"}


def test_next_best_observation_uses_candidate_diversity():
    observation = OrchidObservation(
        observation_id="obs:2",
        characters=(CharacterObservation(character="flower_shape", state="observed", value="round"),),
    )
    result = choose_next_best_observation(
        observation,
        (
            {"lip_structure": "three-lobed", "fragrance": "night"},
            {"lip_structure": "entire", "fragrance": "night"},
            {"lip_structure": "saccate", "fragrance": "day"},
        ),
    )
    assert result == "lip_structure"
