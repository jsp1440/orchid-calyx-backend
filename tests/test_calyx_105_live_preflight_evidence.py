from runtime.calyx_certification.live_preflight_evidence import (
    validate_live_preflight_evidence,
)


def _payload():
    return {
        "run_id": "run-1",
        "deployed_commit_sha": "abc123",
        "route_reachable": True,
        "owner_authenticated": True,
        "database_connected": True,
        "persistent_mount_writable": True,
        "dry_run_directory_writable": True,
        "production_mutation_count": 0,
        "captured_at": "2026-08-04T00:00:00Z",
    }


def test_accepts_complete_no_mutation_evidence():
    result = validate_live_preflight_evidence(_payload())
    assert result["evidence_accepted"] is True
    assert result["production_action_authorized"] is False


def test_rejects_mutation():
    payload = _payload()
    payload["production_mutation_count"] = 1
    assert "production_mutation_detected" in validate_live_preflight_evidence(payload)["blockers"]
