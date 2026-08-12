from runtime.matrix_identification_session import recommend_next_observation

CONCEPT_ID = "11111111-1111-4111-8111-111111111111"


def _candidate(taxon_id, zero_state, weighted_state):
    return {
        "taxon_id": taxon_id,
        "scientific_name": taxon_id,
        "states": {
            "zero_weight_character": zero_state,
            "weighted_character": weighted_state,
        },
    }


def test_zero_weight_character_cannot_outrank_positive_weight_character():
    registry = {
        "characters": [
            {
                "character": "zero_weight_character",
                "label": "Zero weight",
                "weight": 0,
                "concept_id": None,
            },
            {
                "character": "weighted_character",
                "label": "Weighted",
                "weight": 2,
                "concept_id": CONCEPT_ID,
            },
        ],
        "candidates": [
            _candidate("a", "state-a", "state-a"),
            _candidate("b", "state-b", "state-b"),
        ],
    }
    ranked = [{"taxon_id": "a"}, {"taxon_id": "b"}]

    result = recommend_next_observation(registry, ranked, set())

    assert result["character"] == "weighted_character"
    assert result["matrix_weight"] == 2
    assert result["concept_id"] == CONCEPT_ID


def test_selected_next_observation_retains_null_concept_when_unmapped():
    registry = {
        "characters": [
            {
                "character": "flower_shape",
                "label": "Flower shape",
                "weight": 1,
                "concept_id": None,
            },
        ],
        "candidates": [
            {"taxon_id": "a", "states": {"flower_shape": "round"}},
            {"taxon_id": "b", "states": {"flower_shape": "stellate"}},
        ],
    }

    result = recommend_next_observation(
        registry,
        [{"taxon_id": "a"}, {"taxon_id": "b"}],
        set(),
    )

    assert result["character"] == "flower_shape"
    assert result["concept_id"] is None


def test_zero_weight_only_character_is_not_recommended():
    registry = {
        "characters": [
            {
                "character": "zero_weight_character",
                "label": "Zero weight",
                "weight": 0,
                "concept_id": CONCEPT_ID,
            },
        ],
        "candidates": [
            {"taxon_id": "a", "states": {"zero_weight_character": "a"}},
            {"taxon_id": "b", "states": {"zero_weight_character": "b"}},
        ],
    }

    result = recommend_next_observation(
        registry,
        [{"taxon_id": "a"}, {"taxon_id": "b"}],
        set(),
    )

    assert result is None
