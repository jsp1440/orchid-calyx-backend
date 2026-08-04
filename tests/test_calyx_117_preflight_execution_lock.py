from runtime.calyx_certification.preflight_execution_lock import (
    evaluate_preflight_execution_lock,
)


def test_accepts_single_active_lock():
    result = evaluate_preflight_execution_lock(
        {
            "lock_id": "lock-1",
            "holder": "operator",
            "acquired_at": "2026-08-04T00:00:00Z",
            "expires_at": "2026-08-04T01:00:00Z",
            "evaluated_at": "2026-08-04T00:30:00Z",
            "active": True,
            "concurrent_run_count": 1,
        }
    )
    assert result["exclusive_lock_confirmed"] is True


def test_rejects_concurrent_execution():
    result = evaluate_preflight_execution_lock(
        {
            "lock_id": "lock-1",
            "holder": "operator",
            "acquired_at": "2026-08-04T00:00:00Z",
            "expires_at": "2026-08-04T01:00:00Z",
            "evaluated_at": "2026-08-04T00:30:00Z",
            "active": True,
            "concurrent_run_count": 2,
        }
    )
    assert "concurrent_preflight_execution" in result["blockers"]
