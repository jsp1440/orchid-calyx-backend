from runtime.runtime_engine import RuntimeEngine


def ok():
    return {"status": "ok"}


def no_jobs():
    return {"status": "no_jobs", "completed": 0, "failed": 0}


def test_runtime_can_start_when_enabled_by_default():
    engine = RuntimeEngine(
        heartbeat=ok,
        enqueue_jobs=ok,
        execute_jobs=no_jobs,
        enabled=True,
    )

    try:
        assert engine.start() is True
        status = engine.status()
        assert status["enabled"] is True
        assert status["running"] is True
        assert status["thread_alive"] is True
        assert status["started_at"] is not None
    finally:
        engine.stop()


def test_manual_start_can_enable_disabled_engine_before_starting():
    engine = RuntimeEngine(
        heartbeat=ok,
        enqueue_jobs=ok,
        execute_jobs=no_jobs,
        enabled=False,
    )

    assert engine.start() is False
    assert engine.status()["enabled"] is False

    engine.set_enabled(True)
    try:
        assert engine.start() is True
        status = engine.status()
        assert status["enabled"] is True
        assert status["running"] is True
        assert status["thread_alive"] is True
    finally:
        engine.stop()


def test_runtime_cycle_increments_cycle_count():
    engine = RuntimeEngine(
        heartbeat=ok,
        enqueue_jobs=ok,
        execute_jobs=no_jobs,
        enabled=True,
    )

    before = engine.status()["cycle_count"]
    result = engine.run_cycle()
    after = engine.status()["cycle_count"]

    assert result["status"] == "completed"
    assert after == before + 1
    assert engine.status()["last_heartbeat_status"] == "ok"
    assert engine.status()["last_execute_status"] == "no_jobs"
