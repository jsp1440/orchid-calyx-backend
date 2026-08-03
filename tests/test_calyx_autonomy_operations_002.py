from app.calyx_orchestrator.approved_tasks import (
    APPROVED_TASKS,
    PROHIBITED_AUTONOMOUS_ACTIONS,
    ApprovedTask,
    task_profile,
    task_provider_status,
    validate_task,
)


def test_scientific_priorities_precede_support_work():
    profile = task_profile()
    priorities = {task.job_type: task.priority for task in profile}
    assert priorities["taxonomy_readiness"] < priorities["website_design_audit"]
    assert priorities["knowledge_graph_quality"] < priorities["education_readiness"]
    assert priorities["matrix_readiness"] < priorities["harvester_readiness"]


def test_every_approved_task_is_read_only_and_unattended_safe():
    assert APPROVED_TASKS
    for task in APPROVED_TASKS:
        validate_task(task)
        assert task.read_only is True
        assert task.requires_owner_approval is False


def test_mutating_task_is_rejected():
    try:
        validate_task(ApprovedTask("bad", 1, "Bad", "mutate", read_only=False))
    except ValueError as exc:
        assert str(exc) == "AUTONOMOUS_TASK_MUST_BE_READ_ONLY"
    else:
        raise AssertionError("mutating autonomous task was accepted")


def test_prohibited_actions_and_activation_gates_are_explicit():
    status = task_provider_status()
    assert "merge_pull_request" in PROHIBITED_AUTONOMOUS_ACTIONS
    assert "publish_scientific_knowledge" in PROHIBITED_AUTONOMOUS_ACTIONS
    assert status["production_activation"] is False
    assert status["scientific_publication_authority"] is False
