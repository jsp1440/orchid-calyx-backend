from runtime.calyx_certification.worker_readiness import validate_worker_readiness


def test_dry_run_worker_is_ready():
    result = validate_worker_readiness(
        {
            "worker_name": "calyx-worker",
            "heartbeat_at": "2026-08-04T00:00:00Z",
            "queue_connected": True,
            "dry_run_mode": True,
        }
    )
    assert result["worker_ready"] is True


def test_non_dry_run_worker_blocks():
    result = validate_worker_readiness(
        {
            "worker_name": "calyx-worker",
            "heartbeat_at": "2026-08-04T00:00:00Z",
            "queue_connected": True,
            "dry_run_mode": False,
        }
    )
    assert "worker_not_in_dry_run" in result["blockers"]
