from runtime.calyx_certification.owner_decision_lifecycle import (
    evaluate_owner_decision_lifecycle,
)


def test_accepts_current_owner_approval_record():
    result = evaluate_owner_decision_lifecycle(
        {
            "decision_id": "decision-1",
            "snapshot_hash": "snapshot",
            "owner_id": "owner",
            "decided_at": "2026-08-04T00:00:00Z",
            "decision": "approved",
            "expired": False,
            "revoked": False,
        }
    )
    assert result["approved_current"] is True
    assert result["production_action_authorized"] is False


def test_rejects_revoked_approval():
    result = evaluate_owner_decision_lifecycle(
        {
            "decision_id": "decision-1",
            "snapshot_hash": "snapshot",
            "owner_id": "owner",
            "decided_at": "2026-08-04T00:00:00Z",
            "decision": "approved",
            "expired": False,
            "revoked": True,
        }
    )
    assert "owner_decision_revoked" in result["blockers"]
