from runtime.calyx_closed_loop import run_closed_loop_cycle
from runtime.calyx_execution_feedback import ExecutionEvidencePacket
from runtime.calyx_queue_director import DevelopmentIntent


def intent():
    return DevelopmentIntent(
        source_key="frontend-660",
        issue_number=660,
        title="Prepared work",
        repo="orchid-continuum-frontend",
        objective="bounded work",
        acceptance_criteria=("tests pass",),
    )


def complete():
    return ExecutionEvidencePacket(
        task_key="task-660",
        source_key="frontend-660",
        repo="orchid-continuum-frontend",
        issue_number=660,
        state="completed",
        exact_head_sha="a" * 40,
        pr_number=1491,
        tests_passed=True,
        ci_conclusion="success",
        evidence={"ci": "exact-head-green"},
    )


def revise():
    return ExecutionEvidencePacket(
        task_key="task-660",
        source_key="frontend-660",
        repo="orchid-continuum-frontend",
        issue_number=660,
        state="completed",
        exact_head_sha="a" * 40,
        pr_number=1491,
        tests_passed=False,
        ci_conclusion="failure",
        evidence={"ci": "failed"},
    )


def test_completed_semantic_key_survives_restart_and_suppresses_recreation():
    first = run_closed_loop_cycle(intents=[intent()], snapshot={}, execution_evidence=[complete()])
    state = first["persisted_state"]
    assert state["completed_semantic_keys"] == ["calyx-director:frontend-660"]

    restarted = run_closed_loop_cycle(
        intents=[intent()],
        snapshot={},
        execution_evidence=[],
        persisted_state=state,
    )
    assert restarted["refill"]["proposals"] == []
    assert restarted["persisted_state"]["completed_semantic_keys"] == [
        "calyx-director:frontend-660"
    ]


def test_identical_revision_feedback_is_edge_triggered_once_across_restart():
    first = run_closed_loop_cycle(intents=[intent()], snapshot={}, execution_evidence=[revise()])
    assert len(first["revision_requests"]) == 1

    restarted = run_closed_loop_cycle(
        intents=[intent()],
        snapshot={},
        execution_evidence=[revise()],
        persisted_state=first["persisted_state"],
    )
    assert restarted["revision_requests"] == []
    assert restarted["persisted_state"] == first["persisted_state"]
