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
    priorities = {task.domain: task.priority for task in profile}
    assert priorities["taxonomy"] < priorities["website"]
    assert priorities["knowledge_graph"] < priorities["education"]
    assert priorities["matrix"] < priorities["harvesters"]


def test_every_approved_task_is_read_only_and_executable():
    assert APPROVED_TASKS
    executable = {
        "capability_inventory",
        "brain_audit",
        "mission_control_audit",
        "journalism_readiness",
        "archive_readiness",
        "harvester_readiness",
        "deployment_readiness",
        "website_design_audit",
        "education_readiness",
    }
    for task in APPROVED_TASKS:
        validate_task(task)
        assert task.read_only is True
        assert task.requires_owner_approval is False
        assert task.job_type in executable


def test_mutating_task_is_rejected():
    task = ApprovedTask("bad", "capability_inventory", 1, "Bad", "mutate", read_only=False)
    try:
        validate_task(task)
    except ValueError as exc:
        assert str(exc) == "AUTONOMOUS_TASK_MUST_BE_READ_ONLY"
    else:
        raise AssertionError("mutating autonomous task was accepted")


def test_prohibited_actions_and_activation_gates_are_explicit():
    status = task_provider_status()
    assert status["provider"] == "reviewed-static-v2"
    assert "merge_pull_request" in PROHIBITED_AUTONOMOUS_ACTIONS
    assert "publish_scientific_knowledge" in PROHIBITED_AUTONOMOUS_ACTIONS
    assert status["production_activation"] is False
    assert status["scientific_publication_authority"] is False
