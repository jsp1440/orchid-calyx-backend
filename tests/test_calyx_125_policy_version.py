from runtime.calyx_certification.policy_version import validate_policy_version


def test_matching_policy_version_passes():
    result = validate_policy_version(
        {
            "policy_name": "production-certification",
            "policy_version": "1.0",
            "approved_version": "1.0",
            "effective_at": "2026-08-04T00:00:00Z",
        }
    )
    assert result["policy_current"] is True
    assert result["production_action_authorized"] is False


def test_mismatch_blocks():
    result = validate_policy_version(
        {
            "policy_name": "production-certification",
            "policy_version": "1.1",
            "approved_version": "1.0",
            "effective_at": "2026-08-04T00:00:00Z",
        }
    )
    assert "policy_version_mismatch" in result["blockers"]
