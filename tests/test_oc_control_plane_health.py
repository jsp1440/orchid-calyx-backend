from scripts.oc_control_plane_health import UNKNOWN, build_health, classify_ci


def test_runner_zero_with_no_steps_is_external_infrastructure_not_code_failure():
    result = classify_ci([{"id": 42, "status": "completed", "conclusion": "failure", "jobs": [
        {"conclusion": "failure", "runner_id": 0, "steps": []}
    ]}])
    assert result == {
        "state": "EXTERNAL_INFRASTRUCTURE_BLOCKED",
        "reason": "runner_allocation_failure",
        "run_id": 42,
        "runner_id": 0,
        "executed_step_count": 0,
    }


def test_executed_failure_is_kept_separate_from_infrastructure_failure():
    result = classify_ci([{"id": 43, "status": "completed", "conclusion": "failure", "jobs": [
        {"conclusion": "failure", "runner_id": 9, "steps": [{"conclusion": "failure"}]}
    ]}])
    assert result["state"] == "CODE_OR_CHECK_FAILURE"


def test_in_progress_run_is_unknown_not_fabricated_code_failure():
    # A queued/in-progress run has no failure evidence yet; classifying it as a
    # code failure would fabricate production status on every active pulse.
    for status in ("queued", "in_progress"):
        result = classify_ci([{"id": 45, "status": status, "conclusion": None, "jobs": []}])
        assert result["state"] == UNKNOWN
        assert result["run_id"] == 45


def test_unknown_values_are_not_fabricated_as_zero():
    health = build_health({"issues": []})
    assert health["stale_lease_count"] == UNKNOWN
    assert health["duplicate_authoritative_mission_count"] == UNKNOWN
    assert health["last_successful_exact_head_validation"] == UNKNOWN


def test_zero_running_reason_uses_runner_evidence():
    health = build_health({
        "issues": [{"number": 1193, "labels": ["oc-queued", "oc-p0"]}],
        "scheduler_runs": [{"id": 44, "status": "completed", "conclusion": "failure", "jobs": [
            {"conclusion": "failure", "runner_id": 0, "steps": []}
        ]}],
    })
    assert health["current_running_lease"] is None
    assert health["reason_no_work_running"] == "scheduler_job_never_received_a_runner"
