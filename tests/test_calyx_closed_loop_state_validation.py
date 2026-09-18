import pytest

from app.runtime.calyx_closed_loop import run_closed_loop_cycle


def test_closed_loop_rejects_wrong_persisted_schema():
    with pytest.raises(ValueError, match="CALYX_CLOSED_LOOP_STATE_SCHEMA_INVALID"):
        run_closed_loop_cycle(
            intents=[],
            snapshot={},
            persisted_state={
                "schema": "unexpected",
                "seen_feedback_fingerprints": [],
                "completed_semantic_keys": [],
            },
        )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("seen_feedback_fingerprints", "not-a-list", "CALYX_CLOSED_LOOP_SEEN_FEEDBACK_INVALID"),
        ("seen_feedback_fingerprints", [1], "CALYX_CLOSED_LOOP_SEEN_FEEDBACK_INVALID"),
        ("completed_semantic_keys", "not-a-list", "CALYX_CLOSED_LOOP_COMPLETED_KEYS_INVALID"),
        ("completed_semantic_keys", [1], "CALYX_CLOSED_LOOP_COMPLETED_KEYS_INVALID"),
    ],
)
def test_closed_loop_rejects_corrupt_restart_collections(field, value, error):
    state = {
        "schema": "oc.calyx-closed-loop-state.v1",
        "seen_feedback_fingerprints": [],
        "completed_semantic_keys": [],
    }
    state[field] = value
    with pytest.raises((TypeError, ValueError), match=error):
        run_closed_loop_cycle(intents=[], snapshot={}, persisted_state=state)
