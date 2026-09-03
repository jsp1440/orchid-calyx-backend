"""Focused regression tests for the Meta-Orchestrator planner (issue #1129).

All tests use in-memory capability profile fixtures — no database or
external service dependency.

Invariants verified:
- deterministic plan for identical inputs + capability snapshot;
- minimum-sufficient-authority selection;
- empirical metrics cannot select unregistered/ineligible role;
- high consequence always requires human gate;
- no candidate → blocked task, never authority escalation;
- no execution side effects;
- explicit prohibition on policy/permission/self-approval mutation.
"""

from __future__ import annotations

import pytest

from app.calyx_orchestrator.meta_orchestrator import (
    HIGH_CONSEQUENCE_CLASSES,
    MANDATORY_REAUTHORIZATION,
    POLICY_PROHIBITION,
    SCHEMA_VERSION,
    plan,
    is_deterministic,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _profile(
    role_key: str,
    *,
    authoritative: bool = True,
    eligible: bool = True,
    authority_ceiling: str = "A0",
    external_side_effects: bool = False,
    workspace_mutation: bool = False,
    repository_code_execution: bool = False,
    success_rate: float | None = None,
    job_count: int = 0,
) -> dict:
    return {
        "role_key": role_key,
        "executor_key": f"{role_key}_v1",
        "registration_state": "registered",
        "authoritative": authoritative,
        "eligible_for_autonomous_execution": eligible,
        "external_side_effects": external_side_effects,
        "workspace_mutation": workspace_mutation,
        "repository_code_execution": repository_code_execution,
        "authority_ceiling": authority_ceiling,
        "empirical": {
            "observed_job_count": job_count,
            "descriptive_success_rate": success_rate,
            "semantics": "historical_observation_not_predictive_certainty",
        },
        "authority_boundary": {
            "empirical_metrics_do_not_expand_authority": True,
        },
    }


PROBE_PROFILE = _profile("autonomy_probe", authority_ceiling="A0", success_rate=0.95)
READER_PROFILE = _profile(
    "repository_evidence", authority_ceiling="A0", success_rate=0.80
)
PATCHER_PROFILE = _profile(
    "isolated_patch",
    authority_ceiling="A2",
    workspace_mutation=True,
    success_rate=0.70,
)
EXECUTOR_PROFILE = _profile(
    "code_executor",
    authority_ceiling="A3",
    workspace_mutation=True,
    repository_code_execution=True,
    success_rate=0.60,
)
INELIGIBLE_PROFILE = _profile(
    "unregistered_legacy",
    authoritative=False,
    eligible=False,
    authority_ceiling="NONE",
    success_rate=1.0,
)

STANDARD_PROFILES = [
    PROBE_PROFILE,
    READER_PROFILE,
    PATCHER_PROFILE,
    EXECUTOR_PROFILE,
    INELIGIBLE_PROFILE,
]


def _read_task(task_id: str = "t1", minimum: str = "A0") -> dict:
    return {
        "task_id": task_id,
        "objective": "Read repository evidence",
        "consequence_class": "read_only",
        "minimum_required_authority": minimum,
        "allowed_role_keys": [],
        "memory_reference_ids": [],
    }


def _request(consequence: str, tasks: list[dict]) -> dict:
    return {
        "objective": "Test orchestration plan",
        "consequence_class": consequence,
        "tasks": tasks,
    }


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_plan_is_deterministic_for_same_inputs():
    req = _request("read_only", [_read_task()])
    assert is_deterministic(req, STANDARD_PROFILES)


def test_determinism_with_fixed_plan_id():
    req = _request("read_only", [_read_task()])
    p1 = plan(req, STANDARD_PROFILES, plan_id="stable-id")
    p2 = plan(req, STANDARD_PROFILES, plan_id="stable-id")
    assert p1["plan_fingerprint"] == p2["plan_fingerprint"]
    assert p1["plan_id"] == "stable-id"


def test_different_inputs_produce_different_fingerprints():
    req_a = _request("read_only", [_read_task("t1")])
    req_b = _request("bounded_workspace_mutation", [_read_task("t1")])
    pa = plan(req_a, STANDARD_PROFILES, plan_id="x")
    pb = plan(req_b, STANDARD_PROFILES, plan_id="x")
    assert pa["plan_fingerprint"] != pb["plan_fingerprint"]


# ---------------------------------------------------------------------------
# Minimum-sufficient authority selection
# ---------------------------------------------------------------------------


def test_read_task_selects_a0_not_a2():
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    assert task["authority_ceiling"] == "A0"
    assert task["blocked"] is False


def test_workspace_mutation_task_requires_a2():
    mut_task = {
        "task_id": "t1",
        "objective": "Apply patch",
        "consequence_class": "bounded_workspace_mutation",
        "minimum_required_authority": "A2",
        "allowed_role_keys": [],
        "memory_reference_ids": [],
    }
    req = _request("bounded_workspace_mutation", [mut_task])
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    assert task["authority_ceiling"] == "A2"
    assert task["blocked"] is False


def test_repo_execution_task_requires_a3():
    exec_task = {
        "task_id": "t1",
        "objective": "Run tests in sandbox",
        "consequence_class": "repository_code_execution",
        "minimum_required_authority": "A3",
        "allowed_role_keys": [],
        "memory_reference_ids": [],
    }
    req = _request("repository_code_execution", [exec_task])
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    assert task["authority_ceiling"] == "A3"
    assert task["blocked"] is False


def test_allowed_role_keys_restricts_candidates():
    req = _request(
        "read_only",
        [
            {
                "task_id": "t1",
                "objective": "Probe only",
                "consequence_class": "read_only",
                "minimum_required_authority": "A0",
                "allowed_role_keys": ["autonomy_probe"],
                "memory_reference_ids": [],
            }
        ],
    )
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    assert task["selected_role_key"] == "autonomy_probe"


def test_allowed_role_keys_with_no_eligible_produces_blocked():
    req = _request(
        "read_only",
        [
            {
                "task_id": "t1",
                "objective": "Use unregistered role",
                "consequence_class": "read_only",
                "minimum_required_authority": "A0",
                "allowed_role_keys": ["unregistered_legacy"],
                "memory_reference_ids": [],
            }
        ],
    )
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    assert task["blocked"] is True
    assert task["block_reason"] == "NO_ELIGIBLE_CANDIDATE"
    assert task["selected_role_key"] is None


# ---------------------------------------------------------------------------
# Empirical metrics cannot expand authority
# ---------------------------------------------------------------------------


def test_high_success_rate_does_not_select_ineligible_role():
    # ineligible_legacy has success_rate=1.0 but is not eligible
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    assert task["selected_role_key"] != "unregistered_legacy"


def test_empirical_signal_is_bounded_routing_only():
    # Two A0 roles: probe (0.95) and reader (0.80). Probe should win on success rate.
    a0_only = [PROBE_PROFILE, READER_PROFILE]
    req = _request("read_only", [_read_task()])
    result = plan(req, a0_only)
    task = result["assignments"][0]
    assert task["selected_role_key"] == "autonomy_probe"
    assert (
        task["empirical_signal"]["semantics"]
        == "historical_observation_not_predictive_certainty"
    )


def test_empirical_signal_cannot_raise_authority_below_minimum():
    # Patcher has A2 and success_rate=0.70; probe has A0 and 0.95.
    # Task needs A2 minimum: only patcher qualifies despite lower rate.
    req = _request(
        "bounded_workspace_mutation",
        [
            {
                "task_id": "t1",
                "objective": "Patch files",
                "consequence_class": "bounded_workspace_mutation",
                "minimum_required_authority": "A2",
                "allowed_role_keys": [],
                "memory_reference_ids": [],
            }
        ],
    )
    result = plan(req, STANDARD_PROFILES)
    task = result["assignments"][0]
    # probe (A0) must be rejected; patcher (A2) selected
    assert task["selected_role_key"] == "isolated_patch"
    rejected_keys = {r["role_key"] for r in task["rejected_roles"]}
    assert "autonomy_probe" in rejected_keys
    assert "repository_evidence" in rejected_keys


# ---------------------------------------------------------------------------
# High-consequence always requires human gate
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("cc", sorted(HIGH_CONSEQUENCE_CLASSES))
def test_high_consequence_request_requires_human_gate(cc: str):
    req = _request(cc, [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    assert result["human_gate_required"] is True
    assert result["autonomous_execution_eligible"] is False
    assert len(result["human_gate_reasons"]) >= 1


def test_high_consequence_task_within_low_consequence_request():
    req = _request(
        "read_only",
        [
            {
                "task_id": "t1",
                "objective": "Deploy to production",
                "consequence_class": "production_change",
                "minimum_required_authority": "A3",
                "allowed_role_keys": [],
                "memory_reference_ids": [],
            }
        ],
    )
    result = plan(req, STANDARD_PROFILES)
    assert result["human_gate_required"] is True
    assert result["autonomous_execution_eligible"] is False


# ---------------------------------------------------------------------------
# Blocked task on no candidate, no authority escalation
# ---------------------------------------------------------------------------


def test_no_candidates_produces_blocked_task_not_escalation():
    # Only provide ineligible profile
    req = _request("read_only", [_read_task()])
    result = plan(req, [INELIGIBLE_PROFILE])
    assert result["blocked_task_count"] == 1
    task = result["assignments"][0]
    assert task["blocked"] is True
    assert task["block_reason"] == "NO_ELIGIBLE_CANDIDATE"
    assert task["selected_role_key"] is None


def test_blocked_plan_is_not_autonomous_eligible():
    req = _request("read_only", [_read_task()])
    result = plan(req, [INELIGIBLE_PROFILE])
    assert result["autonomous_execution_eligible"] is False


# ---------------------------------------------------------------------------
# No execution side effects
# ---------------------------------------------------------------------------


def test_plan_has_no_execution_side_effects():
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    boundary = result["boundary"]
    assert boundary["plan_does_not_launch_agents"] is True
    assert boundary["plan_does_not_mutate_state"] is True
    assert boundary["execution_requires_registry_recheck"] is True


# ---------------------------------------------------------------------------
# Mandatory reauthorization and policy prohibition
# ---------------------------------------------------------------------------


def test_plan_carries_mandatory_reauthorization():
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    assert MANDATORY_REAUTHORIZATION in result["mandatory_reauthorization_statement"]


def test_plan_carries_policy_prohibition():
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    prohibition = result["authority_prohibition"]
    assert "self-approve" in prohibition or "self_approve" in prohibition or "No role may" in prohibition
    boundary = result["boundary"]
    assert boundary["self_approval_prohibited"] is True
    assert boundary["plan_does_not_grant_authority"] is True


# ---------------------------------------------------------------------------
# Schema and structure
# ---------------------------------------------------------------------------


def test_plan_schema_version():
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    assert result["schema_version"] == SCHEMA_VERSION


def test_plan_has_all_required_fields():
    req = _request("read_only", [_read_task()])
    result = plan(req, STANDARD_PROFILES)
    required_keys = {
        "schema_version",
        "plan_id",
        "plan_fingerprint",
        "objective",
        "consequence_class",
        "autonomous_execution_eligible",
        "human_gate_required",
        "human_gate_reasons",
        "assignments",
        "blocked_task_count",
        "memory_references",
        "mandatory_reauthorization_statement",
        "verification_requirement",
        "authority_prohibition",
        "boundary",
    }
    assert required_keys <= set(result.keys())


def test_memory_references_collected_from_tasks():
    req = _request(
        "read_only",
        [
            {
                "task_id": "t1",
                "objective": "Task with memory",
                "consequence_class": "read_only",
                "minimum_required_authority": "A0",
                "allowed_role_keys": [],
                "memory_reference_ids": ["mem-001", "mem-002"],
            }
        ],
    )
    result = plan(req, STANDARD_PROFILES)
    assert "mem-001" in result["memory_references"]
    assert "mem-002" in result["memory_references"]


# ---------------------------------------------------------------------------
# Multi-task plan
# ---------------------------------------------------------------------------


def test_multi_task_plan_selects_minimum_authority_per_task():
    req = _request(
        "bounded_workspace_mutation",
        [
            _read_task("t1", minimum="A0"),
            {
                "task_id": "t2",
                "objective": "Patch workspace",
                "consequence_class": "bounded_workspace_mutation",
                "minimum_required_authority": "A2",
                "allowed_role_keys": [],
                "memory_reference_ids": [],
            },
        ],
    )
    result = plan(req, STANDARD_PROFILES)
    assert len(result["assignments"]) == 2
    by_task = {a["task_id"]: a for a in result["assignments"]}
    assert by_task["t1"]["authority_ceiling"] == "A0"
    assert by_task["t2"]["authority_ceiling"] == "A2"
    assert result["blocked_task_count"] == 0


def test_empty_tasks_produces_eligible_plan():
    req = _request("read_only", [])
    result = plan(req, STANDARD_PROFILES)
    assert result["blocked_task_count"] == 0
    assert result["autonomous_execution_eligible"] is True
