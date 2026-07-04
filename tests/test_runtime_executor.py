from runtime.runtime_executor import RuntimeExecutor


def test_runtime_executor_runs_limited_queue(tmp_path):
    executor = RuntimeExecutor(execution_dir=tmp_path)
    result = executor.execute_queue(limit=1)

    assert result["build"] == "BUILD-012D"
    assert result["status"] == "completed"
    assert result["executed_count"] == 1
    assert result["executions"][0]["status"] == "completed"


def test_runtime_executor_history(tmp_path):
    executor = RuntimeExecutor(execution_dir=tmp_path)
    executor.execute_queue(limit=1)
    history = executor.history()

    assert history["total_executions"] == 1
    assert history["completed"] == 1
    assert history["success_rate"] == 1.0


def test_runtime_executor_events(tmp_path):
    executor = RuntimeExecutor(execution_dir=tmp_path)
    executor.execute_queue(limit=1)
    events = executor.events()

    assert events["count"] >= 2
    assert any(event["event_type"] == "execution_completed" for event in events["events"])
