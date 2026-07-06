from runtime.runtime_engine import RuntimeEngine


def noop_result(status="ok"):
    return {"status": status}


def test_manual_start_enables_previously_disabled_runtime():
    engine = RuntimeEngine(
        heartbeat=lambda: noop_result(),
        enqueue_jobs=lambda: noop_result(),
        execute_jobs=lambda: {"status": "no_jobs", "completed": 0, "failed": 0},
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
        assert status["started_at"] is not None
    finally:
        engine.stop()


def test_duplicate_start_does_not_create_second_worker():
    engine = RuntimeEngine(
        heartbeat=lambda: noop_result(),
        enqueue_jobs=lambda: noop_result(),
        execute_jobs=lambda: {"status": "no_jobs", "completed": 0, "failed": 0},
        enabled=True,
    )

    try:
        assert engine.start() is True
        assert engine.start() is False
        assert engine.status()["thread_alive"] is True
    finally:
        engine.stop()
