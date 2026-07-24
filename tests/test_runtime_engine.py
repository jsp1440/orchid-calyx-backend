from runtime.runtime_engine import RuntimeEngine


def test_runtime_engine_cycle_updates_status():
    engine = RuntimeEngine(
        heartbeat=lambda: {"overall_status": "healthy"},
        enqueue_jobs=lambda: {"status": "ok"},
        execute_jobs=lambda: {
            "status": "completed",
            "completed": 1,
            "failed": 0,
            "job_name": "audit_pollinator_relationships",
        },
        interval_seconds=30,
        enabled=True,
    )

    result = engine.run_cycle()
    status = engine.status()

    assert result["status"] == "completed"
    assert status["cycle_count"] == 1
    assert status["last_heartbeat_status"] == "healthy"
    assert status["last_enqueue_status"] == "ok"
    assert status["last_execute_status"] == "completed"
    assert status["last_completed_job"] == "audit_pollinator_relationships"
    assert status["current_blocker"] is None


def test_runtime_engine_does_not_start_when_disabled():
    engine = RuntimeEngine(
        heartbeat=lambda: {"overall_status": "healthy"},
        enqueue_jobs=lambda: {"status": "ok"},
        execute_jobs=lambda: {"status": "queue_empty"},
        enabled=False,
    )

    assert engine.start() is False
    assert engine.status()["running"] is False
