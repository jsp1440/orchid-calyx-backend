from __future__ import annotations

import json
from datetime import UTC, datetime

from app.calyx_orchestrator.experience_memory import project_program_experience
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)

NOW = datetime(2026, 8, 22, 9, 30, tzinfo=UTC)


def _program() -> CalyxProgram:
    return CalyxProgram(
        program_id="program-1",
        owner="owner:test",
        title="Experience fixture",
        objective="Prove the autonomous loop and retain useful execution lessons.",
        status="completed",
        max_active_jobs=6,
        paused=False,
        cancellation_reason=None,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
    )


def _job(
    *,
    job_id: str,
    key: str,
    role: str,
    outcome: str,
    attempts: int = 1,
    blocker: str | None = None,
    human_action: str | None = None,
    evidence: dict | None = None,
) -> CalyxProgramJob:
    return CalyxProgramJob(
        program_job_id=job_id,
        program_id="program-1",
        orchestrator_job_id=f"orchestrator-{job_id}",
        job_key=key,
        role_key=role,
        title=key.replace("-", " ").title(),
        repository="jsp1440/orchid-calyx-backend",
        branch="oc-autonomous-integration",
        mutating=role == "isolated_patch",
        input_json=json.dumps({"target": key}),
        work_fingerprint=(key * 64)[:64],
        status="completed" if outcome in {"DELIVERED", "NO_OP"} else "blocked",
        outcome=outcome,
        evidence_json=json.dumps(evidence or {}, sort_keys=True),
        blocker=blocker,
        human_action=human_action,
        attempt_count=attempts,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW,
    )


def _receipt(*, executor: str, secret_output: str = "do-not-retain") -> dict:
    return {
        "receipt_type": "execution",
        "assignment_id": "job-1",
        "program_id": "program-1",
        "job_key": "inspect",
        "executor_key": executor,
        "state": "delivered",
        "input_checksum": "a" * 64,
        "output_checksum": "b" * 64,
        "output": {"status": "delivered", "private_detail": secret_output},
        "evidence_uris": ["calyx:program-job/job-1", "github:commit/abc"],
        "blocker_code": None,
    }


def test_experience_projection_is_deterministic_and_non_authoritative():
    program = _program()
    job = _job(
        job_id="job-1",
        key="inspect",
        role="repository_evidence",
        outcome="DELIVERED",
        evidence=_receipt(executor="repository_evidence_v1"),
    )

    first = project_program_experience(program, (job,), ())
    second = project_program_experience(program, (job,), ())

    assert first["experience_fingerprint"] == second["experience_fingerprint"]
    assert first["authority"] == "non_authoritative_experience_memory"
    assert first["learning_boundary"] == {
        "may_inform_future_planning": True,
        "automatic_policy_rewrite": False,
        "automatic_permission_expansion": False,
        "automatic_production_action": False,
        "scientific_source_evidence": False,
        "private_chain_of_thought_stored": False,
    }


def test_receipt_memory_retains_lineage_but_not_full_executor_output():
    job = _job(
        job_id="job-1",
        key="inspect",
        role="repository_evidence",
        outcome="DELIVERED",
        evidence=_receipt(executor="repository_evidence_v1", secret_output="sensitive"),
    )

    projection = project_program_experience(_program(), (job,), ())
    receipt = projection["jobs"][0]["receipt"]

    assert receipt["executor_key"] == "repository_evidence_v1"
    assert receipt["input_checksum"] == "a" * 64
    assert receipt["output_checksum"] == "b" * 64
    assert receipt["evidence_uris"] == [
        "calyx:program-job/job-1",
        "github:commit/abc",
    ]
    assert receipt["output_keys"] == ["private_detail", "status"]
    assert "sensitive" not in json.dumps(projection)
    assert projection["jobs"][0]["scientific_source_evidence"] is False


def test_recovery_and_success_create_bounded_lesson_candidates():
    job = _job(
        job_id="job-1",
        key="repair",
        role="isolated_patch",
        outcome="DELIVERED",
        attempts=2,
        evidence=_receipt(executor="isolated_patch_v1"),
    )

    projection = project_program_experience(_program(), (job,), ())
    lessons = {item["lesson_type"]: item for item in projection["lesson_candidates"]}

    assert "successful_execution_pattern" in lessons
    assert "recovery_after_retry" in lessons
    for lesson in lessons.values():
        assert lesson["may_inform_planning"] is True
        assert lesson["may_rewrite_policy"] is False
        assert lesson["may_expand_permissions"] is False
        assert lesson["may_trigger_deployment"] is False
        assert lesson["may_publish_scientific_claim"] is False
        assert lesson["confidence_semantics"].startswith("confidence_that_observed_pattern")


def test_blocker_human_escalation_and_dependency_failure_remain_recallable():
    upstream = _job(
        job_id="job-upstream",
        key="validate",
        role="static_validation",
        outcome="BLOCKED",
        blocker="CI_FAILED",
        human_action="Inspect the failing validation.",
    )
    downstream = _job(
        job_id="job-downstream",
        key="publish-candidate",
        role="autonomy_probe",
        outcome="BLOCKED",
        blocker="UPSTREAM_JOB_FAILED",
        human_action="Repair the prerequisite before a new governed revision.",
    )
    dependency = CalyxProgramDependency(
        dependency_id="dep-1",
        program_id="program-1",
        upstream_program_job_id="job-upstream",
        downstream_program_job_id="job-downstream",
        created_at=NOW,
    )

    projection = project_program_experience(
        _program(), (upstream, downstream), (dependency,)
    )
    types = {item["lesson_type"] for item in projection["lesson_candidates"]}

    assert "persistent_blocker" in types
    assert "human_escalation_required" in types
    assert "dependency_failure_propagation" in types
    assert projection["dependencies"] == [
        {
            "dependency_id": "dep-1",
            "upstream_program_job_id": "job-upstream",
            "downstream_program_job_id": "job-downstream",
            "upstream": "validate",
            "downstream": "publish-candidate",
        }
    ]


def test_no_op_becomes_a_candidate_for_future_early_no_op_checks():
    job = _job(
        job_id="job-1",
        key="already-satisfied",
        role="autonomy_probe",
        outcome="NO_OP",
    )

    projection = project_program_experience(_program(), (job,), ())

    assert projection["outcome_counts"] == {"NO_OP": 1}
    assert any(
        item["lesson_type"] == "no_op_pattern"
        for item in projection["lesson_candidates"]
    )
