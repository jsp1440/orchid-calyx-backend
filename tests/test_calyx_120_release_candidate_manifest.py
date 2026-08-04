from runtime.calyx_certification.release_candidate_manifest import (
    build_release_candidate_manifest,
)


def test_builds_valid_release_candidate_manifest():
    result = build_release_candidate_manifest(
        {
            "release_id": "release-1",
            "commit_sha": "abc",
            "snapshot_hash": "snapshot",
            "dependency_manifest_hash": "dependencies",
            "rollback_hash": "rollback",
            "evidence_hashes": ["evidence-1", "evidence-2"],
        }
    )
    assert result["manifest_valid"] is True
    assert result["production_action_authorized"] is False


def test_rejects_duplicate_evidence_hashes():
    result = build_release_candidate_manifest(
        {
            "release_id": "release-1",
            "commit_sha": "abc",
            "snapshot_hash": "snapshot",
            "dependency_manifest_hash": "dependencies",
            "rollback_hash": "rollback",
            "evidence_hashes": ["same", "same"],
        }
    )
    assert "duplicate_evidence_hash" in result["blockers"]
