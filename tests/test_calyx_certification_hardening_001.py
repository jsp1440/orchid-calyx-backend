from runtime.calyx_certification.certification_snapshot import (
    build_certification_snapshot,
)
from runtime.calyx_certification.emergency_halt import evaluate_emergency_halt
from runtime.calyx_certification.live_preflight_evidence import (
    validate_live_preflight_evidence,
)
from runtime.calyx_certification.production_certification_report import (
    build_production_certification_report,
)
from runtime.calyx_certification.release_candidate_manifest import (
    build_release_candidate_manifest,
)


def test_snapshot_accepts_real_bundle_shape_and_structured_blockers():
    result = build_certification_snapshot(
        {"complete": True, "artifact_hash": "bundle", "blockers": []},
        {"status": "ready", "blockers": [{"lane": "graph", "code": "WAIT"}]},
    )
    assert result["certified"] is False
    assert result["blockers"] == [{"lane": "graph", "code": "WAIT"}]
    assert result["production_action_authorized"] is False


def test_report_hash_covers_derived_decision():
    payload = {
        "report_id": "r1",
        "commit_sha": "abcdef1",
        "snapshot_hash": "s",
        "live_evidence_hash": "e",
        "release_gate_hash": "g",
        "owner_decision_id": "o",
        "snapshot_certified": True,
        "live_evidence_accepted": True,
        "dependencies_complete": True,
        "rollback_ready": True,
        "evidence_retained": True,
        "owner_approved_current": True,
        "certification_current": True,
    }
    approved = build_production_certification_report(payload)
    blocked = build_production_certification_report({**payload, "rollback_ready": False})
    assert approved["production_certified"] is True
    assert blocked["production_certified"] is False
    assert approved["report_hash"] != blocked["report_hash"]


def test_signal_only_halt_requires_complete_record():
    result = evaluate_emergency_halt({"signals": ["database_unhealthy"]})
    assert result["halt_required"] is True
    assert result["halt_record_valid"] is False
    assert set(result["blockers"]) == {
        "missing:halt_reason",
        "owner_notification_missing",
        "automated_release_not_disabled",
    }


def test_boolean_mutation_count_is_rejected():
    result = validate_live_preflight_evidence(
        {
            "run_id": "run-1",
            "deployed_commit_sha": "abcdef1",
            "captured_at": "2026-08-04T07:00:00Z",
            "route_reachable": True,
            "owner_authenticated": True,
            "database_connected": True,
            "persistent_mount_writable": True,
            "dry_run_directory_writable": True,
            "production_mutation_count": False,
        }
    )
    assert result["evidence_accepted"] is False
    assert "invalid:production_mutation_count" in result["blockers"]


def test_manifest_hash_is_order_independent_for_evidence_set():
    base = {
        "release_id": "release-1",
        "commit_sha": "abcdef1",
        "snapshot_hash": "s",
        "dependency_manifest_hash": "d",
        "rollback_hash": "r",
    }
    first = build_release_candidate_manifest(
        {**base, "evidence_hashes": ["hash-a", "hash-b"]}
    )
    second = build_release_candidate_manifest(
        {**base, "evidence_hashes": ["hash-b", "hash-a"]}
    )
    assert first["manifest_valid"] is True
    assert first["manifest_hash"] == second["manifest_hash"]
