from runtime.calyx_certification.post_release_verification import (
    evaluate_post_release_verification,
)


def test_accepts_healthy_post_release_state():
    result = evaluate_post_release_verification(
        {
            "release_id": "release-1",
            "expected_commit_sha": "abc",
            "deployed_commit_sha": "abc",
            "verified_at": "2026-08-04T02:00:00Z",
            "route_healthy": True,
            "database_healthy": True,
            "worker_healthy": True,
            "unexpected_mutation_count": 0,
        }
    )
    assert result["post_release_verified"] is True


def test_requires_rollback_evaluation_on_failed_health():
    result = evaluate_post_release_verification(
        {
            "release_id": "release-1",
            "expected_commit_sha": "abc",
            "deployed_commit_sha": "abc",
            "verified_at": "2026-08-04T02:00:00Z",
            "route_healthy": False,
            "database_healthy": True,
            "worker_healthy": True,
            "unexpected_mutation_count": 0,
        }
    )
    assert result["rollback_evaluation_required"] is True
