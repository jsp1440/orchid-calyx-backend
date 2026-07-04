from runtime.autonomous_runner import execute_all_pending_jobs


def test_autonomous_runner_module_imports():
    assert callable(execute_all_pending_jobs)
