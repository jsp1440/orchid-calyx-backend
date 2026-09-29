from __future__ import annotations

import json
from datetime import UTC, datetime

from app.calyx_orchestrator.capability_memory import project_capability_profiles
from app.calyx_orchestrator.program_models import CalyxProgramJob

NOW = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


def _registry() -> dict:
    return {
        "authoritative_roles": ["read", "patch"],
        "executors": [
            {
                "role_key": "read",
                "executor_key": "read_v1",
                "authoritative": True,
                "external_side_effects": False,
                "workspace_mutation": False,
                "repository_code_execution": False,
            },
            {
                "role_key": "patch",
                "executor_key": "patch_v1",
                "authoritative": True,
                "external_side_effects": False,
                "workspace_mutation": True,
                "repository_code_execution": False,
            },
        ],
    }


def _job(
    *,
    job_id: str,
    role: str,
    outcome: str | None,
    attempts: int = 1,
    blocker: str | None = None,
    human_action: str | None = None,
    executor_key: str | None = None,
) -> CalyxProgramJob:
    evidence = {}
    if executor_key:
        evidence = {
            "receipt_type": "execution",
            "executor_key": executor_key,
            "evidence_uris": [f"calyx:job/{job_id}"],
        }
    return CalyxProgramJob(
        program_job_id=job_id,
        program_id=f"program-{job_id}",
        job_key=job_id,
        role_key=role,
        title=job_id,
        repository="jsp1440/orchid-calyx-backend",
        branch="oc-autonomous-integration",
        mutating=role == "patch",
        work_fingerprint=(job_id * 64)[:64],
        status="completed" if outcome in {"DELIVERED", "NO_OP"} else "blocked",
        outcome=outcome,
        evidence_json=json.dumps(evidence),
        blocker=blocker,
        human_action=human_action,
        attempt_count=attempts,
        max_attempts=3,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW if outcome else None,
    )


def _profile(result: dict, role: str) -> dict:
    return next(item for item in result["profiles"] if item["role_key"] == role)


def test_registered_authority_is_static_when_no_experience_exists():
    result = project_capability_profiles(_registry(), ())
    read = _profile(result, "read")
    patch = _profile(result, "patch")

    assert read["authority_ceiling"] == "A0"
    assert patch["authority_ceiling"] == "A2"
    assert read["eligible_for_autonomous_execution"] is True
    assert patch["eligible_for_autonomous_execution"] is True
    assert read["empirical"]["observed_job_count"] == 0
    assert read["empirical"]["descriptive_success_rate"] is None
    assert result["boundary"]["performance_can_change_privilege"] is False


def test_success_and_retry_history_are_descriptive_not_privilege_granting():
    jobs = (
        _job(
            job_id="read-1",
            role="read",
            outcome="DELIVERED",
            attempts=1,
            executor_key="read_v1",
        ),
        _job(
            job_id="read-2",
            role="read",
            outcome="DELIVERED",
            attempts=2,
            executor_key="read_v1",
        ),
    )
    result = project_capability_profiles(_registry(), jobs)
    read = _profile(result, "read")

    assert read["empirical"]["descriptive_success_rate"] == 1.0
    assert read["empirical"]["retry_count"] == 1
    assert read["empirical"]["receipt_coverage"] == 1.0
    assert read["empirical"]["observed_executor_keys"] == ["read_v1"]
    assert read["authority_ceiling"] == "A0"
    assert read["authority_boundary"][
        "historical_success_cannot_raise_authority_ceiling"
    ] is True


def test_blockers_and_human_escalation_are_retained_as_empirical_signals():
    job = _job(
        job_id="patch-1",
        role="patch",
        outcome="BLOCKED",
        attempts=3,
        blocker="CI_FAILED",
        human_action="Inspect CI before a governed retry.",
        executor_key="patch_v1",
    )
    result = project_capability_profiles(_registry(), (job,))
    patch = _profile(result, "patch")

    assert patch["empirical"]["descriptive_success_rate"] == 0.0
    assert patch["empirical"]["retry_count"] == 2
    assert patch["empirical"]["blocker_counts"] == {"CI_FAILED": 1}
    assert patch["empirical"]["human_escalation_count"] == 1
    assert patch["authority_ceiling"] == "A2"
    assert patch["eligible_for_autonomous_execution"] is True


def test_historical_unregistered_role_never_becomes_executable_from_success():
    job = _job(
        job_id="legacy-1",
        role="legacy_superuser",
        outcome="DELIVERED",
        attempts=1,
        executor_key="legacy_superuser_v9",
    )
    result = project_capability_profiles(_registry(), (job,))
    legacy = _profile(result, "legacy_superuser")

    assert legacy["registration_state"] == "historical_unregistered_role"
    assert legacy["authoritative"] is False
    assert legacy["eligible_for_autonomous_execution"] is False
    assert legacy["authority_ceiling"] == "NONE"
    assert legacy["empirical"]["descriptive_success_rate"] == 1.0
    assert legacy["authority_boundary"][
        "historical_success_cannot_restore_registration"
    ] is True
