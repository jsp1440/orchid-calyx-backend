from runtime.calyx_certification.deployed_commit_drift import (
    evaluate_deployed_commit_drift,
)


def test_accepts_aligned_deployed_commit():
    result = evaluate_deployed_commit_drift(
        {
            "deployed_commit_sha": "abc",
            "main_commit_sha": "abc",
            "expected_commit_sha": "abc",
        }
    )
    assert result["aligned"] is True


def test_rejects_deployed_commit_drift():
    result = evaluate_deployed_commit_drift(
        {
            "deployed_commit_sha": "old",
            "main_commit_sha": "new",
            "expected_commit_sha": "new",
        }
    )
    assert "deployed_commit_drift" in result["blockers"]
