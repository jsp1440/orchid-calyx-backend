from runtime.runtime_engine import RuntimeEngine


def test_runtime_engine_constructs_without_explicit_dependencies():
    engine = RuntimeEngine(enabled=False)

    status = engine.status()

    assert status["enabled"] is False
    assert status["running"] is False
    assert status["cycle_count"] == 0


def test_runtime_engine_default_dependencies_are_safe_noops():
    engine = RuntimeEngine(enabled=False)

    result = engine.run_cycle()
    status = engine.status()

    assert result["status"] == "completed"
    assert result["heartbeat"] == {"overall_status": "not_configured"}
    assert result["enqueue"] == {"status": "not_configured", "queue_depth": None}
    assert result["execute"] == {
        "status": "not_configured",
        "completed": 0,
        "failed": 0,
        "queue_depth": None,
    }
    assert status["cycle_count"] == 1
    assert status["last_heartbeat_status"] == "not_configured"
    assert status["last_enqueue_status"] == "not_configured"
    assert status["last_execute_status"] == "not_configured"
    assert status["completed_count"] == 0
    assert status["failed_count"] == 0
    assert status["current_blocker"] is None


def test_runtime_engine_explicit_dependencies_remain_authoritative():
    calls: list[str] = []

    engine = RuntimeEngine(
        heartbeat=lambda: calls.append("heartbeat") or {"overall_status": "healthy"},
        enqueue_jobs=lambda: calls.append("enqueue") or {"status": "queued", "queue_depth": 2},
        execute_jobs=lambda: calls.append("execute")
        or {
            "status": "completed",
            "completed": 1,
            "failed": 0,
            "job_name": "compatibility-check",
            "queue_depth": 1,
        },
        enabled=False,
    )

    result = engine.run_cycle()
    status = engine.status()

    assert result["status"] == "completed"
    assert calls == ["heartbeat", "enqueue", "execute"]
    assert status["last_completed_job"] == "compatibility-check"
    assert status["queue_depth"] == 1
