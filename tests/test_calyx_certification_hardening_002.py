from runtime.calyx_certification.change_window_policy import evaluate_change_window
from runtime.calyx_certification.owner_decision_lifecycle import (
    evaluate_owner_decision_lifecycle,
)
from runtime.calyx_certification.post_release_verification import (
    evaluate_post_release_verification,
)
from runtime.calyx_certification.preflight_execution_lock import (
    evaluate_preflight_execution_lock,
)
from runtime.calyx_certification.secret_readiness import evaluate_secret_readiness


def test_expired_preflight_lock_is_rejected():
    result = evaluate_preflight_execution_lock(
        {
            "lock_id": "lock-1",
            "holder": "worker-1",
            "acquired_at": "2026-08-04T06:00:00Z",
            "expires_at": "2026-08-04T06:30:00Z",
            "evaluated_at": "2026-08-04T07:00:00Z",
            "active": True,
            "concurrent_run_count": 1,
        }
    )
    assert result["exclusive_lock_confirmed"] is False
    assert "preflight_lock_expired" in result["blockers"]


def test_truthy_expired_owner_decision_fails_closed():
    result = evaluate_owner_decision_lifecycle(
        {
            "decision_id": "d1",
            "snapshot_hash": "s1",
            "owner_id": "owner",
            "decided_at": "2026-08-04T07:00:00Z",
            "decision": "approved",
            "expired": "true",
        }
    )
    assert result["approved_current"] is False
    assert "owner_decision_expired" in result["blockers"]


def test_mixed_timezone_window_returns_structured_result():
    result = evaluate_change_window(
        {
            "window_start": "2026-08-04T06:00:00",
            "window_end": "2026-08-04T08:00:00Z",
            "evaluated_at": "2026-08-04T07:00:00Z",
            "owner_window_approved": True,
        }
    )
    assert result["within_approved_window"] is True
    assert result["blockers"] == []


def test_missing_mutation_count_has_precise_blocker():
    result = evaluate_post_release_verification(
        {
            "release_id": "r1",
            "expected_commit_sha": "abc",
            "deployed_commit_sha": "abc",
            "verified_at": "2026-08-04T07:00:00Z",
            "route_healthy": True,
            "database_healthy": True,
            "worker_healthy": True,
        }
    )
    assert result["post_release_verified"] is False
    assert "missing:unexpected_mutation_count" in result["blockers"]
    assert "unexpected_post_release_mutation" not in result["blockers"]


def test_duplicate_secret_entries_cannot_hide_exposure():
    result = evaluate_secret_readiness(
        [
            {
                "name": "CALYX_BACKEND_URL",
                "configured": True,
                "source": "github_actions",
                "value": "secret",
            },
            {
                "name": "CALYX_BACKEND_URL",
                "configured": True,
                "source": "github_actions",
                "value": None,
            },
            {
                "name": "CALYX_OWNER_ACCESS_CODE",
                "configured": True,
                "source": "runtime_environment",
                "value": None,
            },
        ]
    )
    assert result["ready"] is False
    assert "duplicate_name:CALYX_BACKEND_URL" in result["blockers"]
    assert "secret_value_exposed:CALYX_BACKEND_URL" in result["blockers"]
