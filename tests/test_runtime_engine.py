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
    assert result["regulation"]["mission"]["mission_id"] == "oc-mission-v1"
    assert "revealing relationships" in result["regulation"]["mission"]["guiding_principle"]


def test_runtime_engine_does_not_start_when_disabled():
    engine = RuntimeEngine(
        heartbeat=lambda: {"overall_status": "healthy"},
        enqueue_jobs=lambda: {"status": "ok"},
        execute_jobs=lambda: {"status": "queue_empty"},
        enabled=False,
    )

    assert engine.start() is False
    assert engine.status()["running"] is False


def test_runtime_engine_regulator_can_repress_enqueue_and_execution():
    calls = {"enqueue": 0, "execute": 0}

    def enqueue_jobs():
        calls["enqueue"] += 1
        return {"status": "ok"}

    def execute_jobs():
        calls["execute"] += 1
        return {"status": "completed", "completed": 1, "failed": 0}

    engine = RuntimeEngine(
        heartbeat=lambda: {"overall_status": "warning"},
        enqueue_jobs=enqueue_jobs,
        execute_jobs=execute_jobs,
        regulator=lambda heartbeat: {
            "action": "repress",
            "reasons": ["runtime health is not eligible for autonomous execution"],
        },
        enabled=True,
    )

    result = engine.run_cycle()
    status = engine.status()

    assert result["status"] == "completed"
    assert result["regulation"]["action"] == "repress"
    assert result["enqueue"]["status"] == "repressed"
    assert result["execute"]["status"] == "repressed"
    assert calls == {"enqueue": 0, "execute": 0}
    assert status["last_regulatory_action"] == "repress"
    assert status["last_execute_completed"] == 0
    assert status["last_execute_failed"] == 0


def test_runtime_engine_invalid_regulator_output_fails_closed():
    calls = {"enqueue": 0, "execute": 0}

    engine = RuntimeEngine(
        heartbeat=lambda: {"overall_status": "healthy"},
        enqueue_jobs=lambda: calls.__setitem__("enqueue", calls["enqueue"] + 1),
        execute_jobs=lambda: calls.__setitem__("execute", calls["execute"] + 1),
        regulator=lambda heartbeat: {"action": "unknown"},
        enabled=True,
    )

    result = engine.run_cycle()

    assert result["regulation"]["action"] == "escalate"
    assert result["enqueue"]["status"] == "repressed"
    assert result["execute"]["status"] == "repressed"
    assert calls == {"enqueue": 0, "execute": 0}
