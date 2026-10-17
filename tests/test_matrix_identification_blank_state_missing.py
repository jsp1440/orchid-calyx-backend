"""Blank candidate states are missing data, never scored as absence/conflict."""

from __future__ import annotations

import pytest

from runtime.matrix_identification import Candidate, Observation, rank_candidates


def _rank(state):
    report = rank_candidates(
        [
            Observation("lip", "white"),
            Observation("spur", "long"),
        ],
        [
            Candidate("t1", "Alpha blanka", {"lip": "white", "spur": state}),
        ],
    )
    return report["candidates"][0]


@pytest.mark.parametrize("blank", ["", "   ", [], (), set(), ["", "  "]])
def test_blank_candidate_state_is_missing_not_conflict(blank):
    result = _rank(blank)
    by_char = {e["character"]: e for e in result["explanations"]}
    assert by_char["spur"]["status"] == "candidate_state_missing"
    assert by_char["spur"]["similarity"] is None
    # Only the supplied, matching character is compared; absence is not scored.
    assert result["score"] == 1.0
    assert result["coverage"] == 0.5
    assert result["compared_weight"] == 1.0


def test_real_conflict_is_still_scored():
    result = _rank("short")
    by_char = {e["character"]: e for e in result["explanations"]}
    assert by_char["spur"]["status"] == "conflict"
    assert result["score"] == 0.5


def test_falsy_but_real_states_are_not_treated_as_missing():
    report = rank_candidates(
        [Observation("count", 0), Observation("flag", False)],
        [Candidate("t1", "Alpha zeroa", {"count": 0, "flag": False})],
    )
    statuses = {
        e["character"]: e["status"] for e in report["candidates"][0]["explanations"]
    }
    assert statuses == {"count": "matched", "flag": "matched"}
