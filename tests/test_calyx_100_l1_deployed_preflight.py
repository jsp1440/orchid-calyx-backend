from runtime.calyx_certification.deployed_preflight import (
    REQUIRED_CHECKS,
    certify_deployed_preflight,
)


def _report():
    return {
        "run_id": "run:1",
        "deployed_commit_sha": "abc123",
        "artifact_hash": "sha256:test",
        "checks": {name: True for name in REQUIRED_CHECKS},
    }


def test_complete_preflight_certifies_without_authorizing_production():
    result = certify_deployed_preflight(_report())
    assert result["certified"] is True
    assert result["production_action_authorized"] is False
    assert result["owner_authorization_required"] is True


def test_failed_mount_and_missing_hash_block_certification():
    report = _report()
    report["checks"]["persistent_mount_writable"] = False
    report["artifact_hash"] = None
    result = certify_deployed_preflight(report)
    assert result["certified"] is False
    assert "persistent_mount_writable:FAILED" in result["blockers"]
    assert "ARTIFACT_HASH_MISSING" in result["blockers"]
