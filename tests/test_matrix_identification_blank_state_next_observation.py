"""Blank candidate states are missing data for next-observation selection too."""

from __future__ import annotations

import pytest

from runtime.matrix_identification_session import recommend_next_observation


def _registry(spur_states):
    candidates = [
        {"taxon_id": f"t{i}", "states": {"lip": "white", "spur": state}}
        for i, state in enumerate(spur_states)
    ]
    return {
        "characters": [
            {"character": "lip", "weight": 1.0},
            {"character": "spur", "weight": 1.0},
        ],
        "candidates": candidates,
    }


def _recommend(spur_states):
    ranked = [{"taxon_id": f"t{i}"} for i in range(len(spur_states))]
    return recommend_next_observation(_registry(spur_states), ranked, {"lip"})


@pytest.mark.parametrize("blank", ["", "   ", [], (), set(), ["", "  "]])
def test_blank_state_does_not_manufacture_discrimination(blank):
    # One real state against a blank is missing data, not two distinct states.
    assert _recommend(["long", blank]) is None


def test_two_real_distinct_states_are_still_recommended():
    result = _recommend(["long", "short"])
    assert result is not None
    assert result["character"] == "spur"
    assert result["candidate_coverage"] == 1.0
    assert result["distinct_state_count"] == 2


def test_blank_state_reduces_reported_coverage():
    result = _recommend(["long", "short", ""])
    assert result is not None
    assert result["candidate_count"] == 3
    assert result["candidate_coverage"] == pytest.approx(2 / 3, abs=1e-6)
    assert result["distinct_state_count"] == 2
