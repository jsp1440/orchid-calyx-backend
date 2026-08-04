from runtime.calyx_certification.mission_control_readiness import (
    assemble_readiness_view,
)


def test_ready_only_when_snapshot_and_live_evidence_pass():
    result = assemble_readiness_view(
        {"certified": True, "blockers": [], "snapshot_hash": "s"},
        {"evidence_accepted": True, "blockers": [], "artifact_hash": "e"},
    )
    assert result["status"] == "ready"
    assert result["production_action_authorized"] is False


def test_blockers_are_visible():
    result = assemble_readiness_view(
        {"certified": False, "blockers": ["snapshot_blocked"]},
        {"evidence_accepted": False, "blockers": ["live_missing"]},
    )
    assert result["status"] == "blocked"
    assert result["blockers"] == ["live_missing", "snapshot_blocked"]
