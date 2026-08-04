from runtime.calyx_certification.production_certification_report import (
    build_production_certification_report,
)


def _payload() -> dict[str, object]:
    return {
        "report_id": "report-1",
        "commit_sha": "abc",
        "snapshot_hash": "snapshot",
        "live_evidence_hash": "evidence",
        "release_gate_hash": "gate",
        "owner_decision_id": "decision",
        "snapshot_certified": True,
        "live_evidence_accepted": True,
        "dependencies_complete": True,
        "rollback_ready": True,
        "evidence_retained": True,
        "owner_approved_current": True,
        "certification_current": True,
    }


def test_builds_certified_report_without_authorizing_action():
    result = build_production_certification_report(_payload())
    assert result["production_certified"] is True
    assert result["production_action_authorized"] is False


def test_rejects_stale_certification():
    payload = _payload()
    payload["certification_current"] = False
    result = build_production_certification_report(payload)
    assert "failed:certification_current" in result["blockers"]
