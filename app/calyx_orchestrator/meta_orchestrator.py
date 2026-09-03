"""Consequence-aware Meta-Orchestrator planner.

Proposal-only slice: assembles the minimum sufficient executor team for a
structured request, respects consequence and authority requirements, and
returns a governed plan.  This slice does NOT launch agents, mutate program
state, or modify any permission/policy record.

Consequence classes and their human-gate requirement:
    read_only                    → autonomous eligible
    bounded_workspace_mutation   → autonomous eligible
    repository_code_execution    → autonomous eligible
    production_change            → HUMAN GATE required
    scientific_publication       → HUMAN GATE required
    restricted_data_or_security  → HUMAN GATE required
    governance_change            → HUMAN GATE required

Authority ceilings (least to most privileged):
    NONE  < A0  < A2  < A3

Selection rules for each task:
    1. Discard roles not currently registered and autonomously eligible.
    2. Discard roles not in the task's allowed_role_keys (when specified).
    3. Discard roles whose authority_ceiling is below the task's
       minimum_required_authority.
    4. Prefer the least-privileged sufficient authority ceiling.
    5. Among equally privileged candidates, use descriptive_success_rate as
       a bounded routing signal (historical observation, not predictive
       certainty).
    6. Deterministic tie-break: alphabetical by role_key.
    7. Emit a blocked task if no eligible candidate exists.

Plans carry a mandatory execution-time reauthorization statement: at actual
dispatch the executor registry must be rechecked via
``AuthoritativeExecutorRegistry.require_authoritative()`` before assignment.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from enum import Enum
from typing import Any

SCHEMA_VERSION = "calyx-meta-orchestrator/1"

AUTHORITY_ORDER = ("NONE", "A0", "A2", "A3")

HIGH_CONSEQUENCE_CLASSES = frozenset(
    {
        "production_change",
        "scientific_publication",
        "restricted_data_or_security",
        "governance_change",
    }
)

AUTONOMOUS_CONSEQUENCE_CLASSES = frozenset(
    {
        "read_only",
        "bounded_workspace_mutation",
        "repository_code_execution",
    }
)

_CONSEQUENCE_MINIMUM_AUTHORITY: dict[str, str] = {
    "read_only": "A0",
    "bounded_workspace_mutation": "A2",
    "repository_code_execution": "A3",
    "production_change": "A3",
    "scientific_publication": "A0",
    "restricted_data_or_security": "A0",
    "governance_change": "A0",
}

MANDATORY_REAUTHORIZATION = (
    "At execution time, AuthoritativeExecutorRegistry.require_authoritative() "
    "MUST be called immediately before assignment. This plan's role selection "
    "is advisory only; it does not constitute execution authority."
)

POLICY_PROHIBITION = (
    "This plan does not grant, expand, or modify any permission, policy, or "
    "authority. No role may self-approve its own use. No plan output may "
    "autonomously deploy, publish science, mutate production state, or "
    "authorize new credentials."
)


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _authority_rank(ceiling: str) -> int:
    try:
        return AUTHORITY_ORDER.index(ceiling)
    except ValueError:
        return -1


def _sufficient(ceiling: str, minimum: str) -> bool:
    """Return True when ceiling meets or exceeds minimum authority."""
    return _authority_rank(ceiling) >= _authority_rank(minimum)


def _empirical_success_rate(profile: dict[str, Any]) -> float:
    empirical = profile.get("empirical") or {}
    rate = empirical.get("descriptive_success_rate")
    if rate is None:
        return 0.0
    return float(rate)


def _select_role(
    candidates: list[dict[str, Any]],
    minimum_required_authority: str,
    task_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Return (selected_profile | None, list_of_rejection_records)."""
    rejections: list[dict[str, str]] = []
    eligible: list[dict[str, Any]] = []

    for profile in candidates:
        role_key = str(profile.get("role_key", ""))
        if not profile.get("eligible_for_autonomous_execution"):
            rejections.append(
                {
                    "role_key": role_key,
                    "reason": "not_eligible_for_autonomous_execution",
                }
            )
            continue
        ceiling = str(profile.get("authority_ceiling", "NONE"))
        if not _sufficient(ceiling, minimum_required_authority):
            rejections.append(
                {
                    "role_key": role_key,
                    "reason": (
                        f"authority_ceiling_{ceiling}_below_required_"
                        f"{minimum_required_authority}"
                    ),
                }
            )
            continue
        eligible.append(profile)

    if not eligible:
        return None, rejections

    # Sort: least-privileged ceiling first, then descending success rate,
    # then alphabetical role_key for determinism.
    eligible.sort(
        key=lambda p: (
            _authority_rank(str(p.get("authority_ceiling", "NONE"))),
            -_empirical_success_rate(p),
            str(p.get("role_key", "")),
        )
    )
    return eligible[0], rejections


def _resolve_minimum_authority(
    task_minimum: str | None,
    consequence_class: str,
) -> str:
    """Task minimum takes precedence; consequence class sets a floor."""
    floor = _CONSEQUENCE_MINIMUM_AUTHORITY.get(consequence_class, "A0")
    if task_minimum is None:
        return floor
    if _authority_rank(task_minimum) >= _authority_rank(floor):
        return task_minimum
    return floor


def plan(
    request: dict[str, Any],
    capability_profiles: list[dict[str, Any]],
    *,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Produce a governed orchestrator plan.

    Args:
        request: Structured request dict with keys:
            - objective (str)
            - consequence_class (str)
            - tasks (list of task dicts, each with):
                - task_id (str)
                - objective (str)
                - consequence_class (str, overrides request level for this task)
                - minimum_required_authority (str, optional)
                - allowed_role_keys (list[str], optional — empty means all)
                - memory_reference_ids (list[str], optional)
        capability_profiles: Profile list from
            ``capability_memory.project_capability_profiles``.
        plan_id: Optional stable plan id; a UUID4 is generated when absent.

    Returns:
        Governed plan dict.  Never launches agents or mutates state.
    """
    objective = str(request.get("objective", ""))
    consequence_class = str(request.get("consequence_class", "read_only"))
    tasks = list(request.get("tasks") or [])
    plan_id = plan_id or str(uuid.uuid4())

    is_high_consequence = consequence_class in HIGH_CONSEQUENCE_CLASSES
    human_gate_reasons: list[str] = []
    if is_high_consequence:
        human_gate_reasons.append(
            f"consequence_class_{consequence_class}_requires_human_gate"
        )

    profiles_by_role: dict[str, dict[str, Any]] = {
        str(p.get("role_key", "")): p for p in capability_profiles
    }

    assignments: list[dict[str, Any]] = []
    all_memory_refs: list[str] = []

    for task in tasks:
        task_id = str(task.get("task_id", ""))
        task_objective = str(task.get("objective", ""))
        task_consequence = str(
            task.get("consequence_class", consequence_class)
        )
        task_minimum = task.get("minimum_required_authority")
        allowed_keys: list[str] = list(task.get("allowed_role_keys") or [])
        memory_refs: list[str] = list(task.get("memory_reference_ids") or [])
        all_memory_refs.extend(memory_refs)

        effective_minimum = _resolve_minimum_authority(
            task_minimum, task_consequence
        )
        task_high = task_consequence in HIGH_CONSEQUENCE_CLASSES
        if task_high:
            human_gate_reasons.append(
                f"task_{task_id}_consequence_{task_consequence}_requires_human_gate"
            )

        if allowed_keys:
            candidates = [
                p
                for role, p in profiles_by_role.items()
                if role in allowed_keys
            ]
        else:
            candidates = list(profiles_by_role.values())

        selected, rejections = _select_role(
            candidates, effective_minimum, task_id
        )

        if selected is None:
            assignments.append(
                {
                    "task_id": task_id,
                    "objective": task_objective,
                    "consequence_class": task_consequence,
                    "selected_role_key": None,
                    "selected_executor_key": None,
                    "authority_ceiling": None,
                    "selection_rationale": "no_eligible_candidate",
                    "rejected_roles": rejections,
                    "empirical_signal": {},
                    "memory_reference_ids": memory_refs,
                    "blocked": True,
                    "block_reason": "NO_ELIGIBLE_CANDIDATE",
                }
            )
        else:
            empirical = dict(selected.get("empirical") or {})
            empirical.pop("outcome_counts", None)
            empirical.pop("blocker_counts", None)
            role_key = str(selected.get("role_key", ""))
            assignments.append(
                {
                    "task_id": task_id,
                    "objective": task_objective,
                    "consequence_class": task_consequence,
                    "selected_role_key": role_key,
                    "selected_executor_key": selected.get("executor_key"),
                    "authority_ceiling": selected.get("authority_ceiling"),
                    "selection_rationale": (
                        "minimum_sufficient_authority_selected"
                        if not task_high
                        else "human_gate_required_plan_advisory_only"
                    ),
                    "rejected_roles": rejections,
                    "empirical_signal": {
                        "descriptive_success_rate": _empirical_success_rate(
                            selected
                        ),
                        "semantics": (
                            "historical_observation_not_predictive_certainty"
                        ),
                        "observed_job_count": empirical.get(
                            "observed_job_count", 0
                        ),
                    },
                    "memory_reference_ids": memory_refs,
                    "blocked": False,
                    "block_reason": None,
                }
            )

    blocked_count = sum(1 for a in assignments if a["blocked"])
    human_gate_required = bool(human_gate_reasons)
    autonomous_eligible = (
        not human_gate_required
        and blocked_count == 0
    )

    verification = (
        "human_review_required_before_any_execution"
        if human_gate_required
        else "executor_registry_recheck_required_at_dispatch_time"
    )

    fingerprint_payload = {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "objective": objective,
        "consequence_class": consequence_class,
        "assignments": [
            {
                "task_id": a["task_id"],
                "selected_role_key": a["selected_role_key"],
                "authority_ceiling": a["authority_ceiling"],
                "blocked": a["blocked"],
            }
            for a in assignments
        ],
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "plan_id": plan_id,
        "plan_fingerprint": _canonical_hash(fingerprint_payload),
        "objective": objective,
        "consequence_class": consequence_class,
        "autonomous_execution_eligible": autonomous_eligible,
        "human_gate_required": human_gate_required,
        "human_gate_reasons": sorted(set(human_gate_reasons)),
        "assignments": assignments,
        "blocked_task_count": blocked_count,
        "memory_references": sorted(set(all_memory_refs)),
        "mandatory_reauthorization_statement": MANDATORY_REAUTHORIZATION,
        "verification_requirement": verification,
        "authority_prohibition": POLICY_PROHIBITION,
        "boundary": {
            "plan_does_not_grant_authority": True,
            "plan_does_not_launch_agents": True,
            "plan_does_not_mutate_state": True,
            "execution_requires_registry_recheck": True,
            "high_consequence_requires_human_gate": True,
            "self_approval_prohibited": True,
        },
    }


def is_deterministic(
    request: dict[str, Any],
    capability_profiles: list[dict[str, Any]],
) -> bool:
    """Verify two independent plan() calls with the same inputs share fingerprints."""
    p1 = plan(request, capability_profiles, plan_id="probe-id")
    p2 = plan(request, capability_profiles, plan_id="probe-id")
    return p1["plan_fingerprint"] == p2["plan_fingerprint"]
