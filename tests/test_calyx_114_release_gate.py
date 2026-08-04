from runtime.calyx_certification.release_gate import evaluate_release_gate


def _ready() -> dict[str, bool]:
    return {
        "snapshot_certified": True,
        "live_evidence_accepted": True,
        "owner_approved": True,
        "dependencies_complete": True,
        "rollback_ready": True,
        "evidence_retained": True,
        "certification_current": True,
    }


def test_complete_gate_is_eligible_but_manual():
    result = evaluate_release_gate(_ready())
    assert result["release_eligible"] is True
    assert result["manual_execution_required"] is True
    assert result["production_action_authorized"] is False


def test_missing_owner_approval_blocks():
    payload = _ready()
    payload["owner_approved"] = False
    result = evaluate_release_gate(payload)
    assert "failed:owner_approved" in result["blockers"]
