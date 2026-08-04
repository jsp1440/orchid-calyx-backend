from runtime.calyx_certification.owner_handoff import build_owner_handoff_package


def test_complete_handoff_is_ready_but_manual():
    result = build_owner_handoff_package(
        {
            "certification_report_hash": "c",
            "release_candidate_hash": "r",
            "blockers": [],
            "recommended_decision": "approve",
            "generated_at": "2026-08-04T00:00:00Z",
        }
    )
    assert result["handoff_ready"] is True
    assert result["owner_decision_required"] is True
    assert result["production_action_authorized"] is False


def test_invalid_decision_blocks():
    result = build_owner_handoff_package(
        {
            "certification_report_hash": "c",
            "release_candidate_hash": "r",
            "blockers": [],
            "recommended_decision": "execute",
            "generated_at": "2026-08-04T00:00:00Z",
        }
    )
    assert "invalid_recommended_decision" in result["blockers"]
