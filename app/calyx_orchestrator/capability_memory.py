from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .executor_registry import AuthoritativeExecutorRegistry
from .program_models import CalyxProgram, CalyxProgramJob

SCHEMA_VERSION = "calyx-capability-memory/1"
SUCCESSFUL_OUTCOMES = frozenset({"DELIVERED", "NO_OP"})


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


def _receipt_metadata(job: CalyxProgramJob) -> tuple[str | None, bool]:
    if not job.evidence_json:
        return None, False
    try:
        payload = json.loads(job.evidence_json)
    except json.JSONDecodeError:
        return None, False
    if not isinstance(payload, dict):
        return None, False
    executor_key = payload.get("executor_key")
    has_receipt = payload.get("receipt_type") in {"execution", "cancellation"}
    return (str(executor_key) if executor_key else None), has_receipt


def _authority_ceiling(executor: dict[str, Any]) -> str:
    if executor.get("external_side_effects"):
        return "DISALLOWED_EXTERNAL_SIDE_EFFECTS"
    if executor.get("repository_code_execution"):
        return "A3"
    if executor.get("workspace_mutation"):
        return "A2"
    return "A0"


def _empirical_stats(jobs: list[CalyxProgramJob]) -> dict[str, Any]:
    outcome_counts = Counter(str(job.outcome or "PENDING") for job in jobs)
    blocker_counts = Counter(str(job.blocker) for job in jobs if job.blocker)
    terminal_jobs = [job for job in jobs if job.outcome is not None]
    successful = sum(job.outcome in SUCCESSFUL_OUTCOMES for job in terminal_jobs)
    receipt_count = 0
    executor_keys: set[str] = set()
    for job in jobs:
        executor_key, has_receipt = _receipt_metadata(job)
        if executor_key:
            executor_keys.add(executor_key)
        if has_receipt:
            receipt_count += 1
    program_ids = {job.program_id for job in jobs}
    last_observed = max((job.updated_at for job in jobs), default=None)
    total_attempts = sum(job.attempt_count for job in jobs)
    retry_count = sum(max(job.attempt_count - 1, 0) for job in jobs)
    return {
        "observed_job_count": len(jobs),
        "observed_program_count": len(program_ids),
        "terminal_job_count": len(terminal_jobs),
        "successful_terminal_count": successful,
        "descriptive_success_rate": (
            successful / len(terminal_jobs) if terminal_jobs else None
        ),
        "success_rate_semantics": "historical_observation_not_predictive_certainty",
        "outcome_counts": dict(sorted(outcome_counts.items())),
        "total_attempts": total_attempts,
        "retry_count": retry_count,
        "average_attempts_per_job": total_attempts / len(jobs) if jobs else None,
        "blocker_counts": dict(sorted(blocker_counts.items())),
        "human_escalation_count": sum(bool(job.human_action) for job in jobs),
        "receipt_coverage": receipt_count / len(jobs) if jobs else None,
        "observed_executor_keys": sorted(executor_keys),
        "last_observed_at": _iso(last_observed),
    }


def project_capability_profiles(
    registry_status: dict[str, Any], jobs: Iterable[CalyxProgramJob]
) -> dict[str, Any]:
    """Combine static executor authority with descriptive owner-scoped experience."""

    jobs_by_role: dict[str, list[CalyxProgramJob]] = defaultdict(list)
    for job in jobs:
        jobs_by_role[job.role_key].append(job)

    registered_by_role = {
        str(item["role_key"]): item
        for item in registry_status.get("executors", [])
        if isinstance(item, dict) and item.get("role_key")
    }
    profiles: list[dict[str, Any]] = []
    all_roles = sorted(set(registered_by_role) | set(jobs_by_role))
    for role_key in all_roles:
        registered = registered_by_role.get(role_key)
        empirical = _empirical_stats(jobs_by_role.get(role_key, []))
        if registered is None:
            profiles.append(
                {
                    "role_key": role_key,
                    "executor_key": None,
                    "registration_state": "historical_unregistered_role",
                    "authoritative": False,
                    "eligible_for_autonomous_execution": False,
                    "external_side_effects": None,
                    "workspace_mutation": None,
                    "repository_code_execution": None,
                    "authority_ceiling": "NONE",
                    "empirical": empirical,
                    "authority_boundary": {
                        "empirical_metrics_do_not_expand_authority": True,
                        "historical_success_cannot_restore_registration": True,
                    },
                }
            )
            continue

        external_side_effects = bool(registered.get("external_side_effects"))
        authoritative = bool(registered.get("authoritative"))
        profiles.append(
            {
                "role_key": role_key,
                "executor_key": registered.get("executor_key"),
                "registration_state": "registered",
                "authoritative": authoritative,
                "eligible_for_autonomous_execution": (
                    authoritative and not external_side_effects
                ),
                "external_side_effects": external_side_effects,
                "workspace_mutation": bool(registered.get("workspace_mutation")),
                "repository_code_execution": bool(
                    registered.get("repository_code_execution")
                ),
                "authority_ceiling": _authority_ceiling(registered),
                "empirical": empirical,
                "authority_boundary": {
                    "empirical_metrics_do_not_expand_authority": True,
                    "historical_success_cannot_raise_authority_ceiling": True,
                    "historical_failure_cannot_bypass_governance": True,
                },
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "registry_authority": "canonical_static_executor_allowlist",
        "empirical_authority": "descriptive_routing_context_only",
        "profiles": profiles,
        "registered_role_count": len(registered_by_role),
        "historical_role_count": len(jobs_by_role),
        "boundary": {
            "performance_can_change_routing_preference": True,
            "performance_can_change_privilege": False,
            "automatic_permission_expansion": False,
            "automatic_external_side_effect_authorization": False,
        },
    }


def load_owner_capability_registry(
    db: Session,
    *,
    owner: str,
    registry: AuthoritativeExecutorRegistry | None = None,
) -> dict[str, Any]:
    """Return static executor authority plus empirical history for one owner only."""

    active_registry = registry or AuthoritativeExecutorRegistry()
    jobs = db.scalars(
        select(CalyxProgramJob)
        .join(CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id)
        .where(CalyxProgram.owner == owner)
        .order_by(CalyxProgramJob.updated_at.asc())
    ).all()
    return project_capability_profiles(active_registry.status(), jobs)
