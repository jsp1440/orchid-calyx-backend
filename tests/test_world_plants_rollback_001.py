import pytest

from runtime.world_plants_rollback import rehearse_promotion_and_rollback


def state() -> dict:
    return {
        "canonical_release_id": "old",
        "releases": {
            "old": {"row_count": 34675, "crosswalk_count": 34675},
            "new": {"row_count": 34724, "crosswalk_count": 34700},
        },
    }


def test_rehearsal_restores_original_state_and_preserves_history():
    result = rehearse_promotion_and_rollback(
        state(),
        candidate_release_id="new",
        actor="owner",
    )
    assert result.certified is True
    assert result.state_restored is True
    assert result.historical_releases_preserved is True
    assert [receipt.action for receipt in result.receipts] == ["promote", "rollback"]


def test_rehearsal_does_not_mutate_input():
    original = state()
    baseline = state()
    rehearse_promotion_and_rollback(
        original,
        candidate_release_id="new",
        actor="owner",
    )
    assert original == baseline


def test_actor_is_required():
    with pytest.raises(ValueError, match="actor is required"):
        rehearse_promotion_and_rollback(
            state(),
            candidate_release_id="new",
            actor="",
        )


def test_candidate_must_exist():
    with pytest.raises(ValueError, match="candidate release not found"):
        rehearse_promotion_and_rollback(
            state(),
            candidate_release_id="missing",
            actor="owner",
        )
