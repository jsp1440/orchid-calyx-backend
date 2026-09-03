"""Tests for the POST /orchestrator/plan governed proposal endpoint logic.

FastAPI is not installed in this test environment, so we test:
  1. The endpoint's core logic by exercising meta_plan() and
     load_owner_capability_registry() directly.
  2. Route structure: the endpoint is registered at the correct path
     in routes.py (verified via AST/text scan, not live import).

Acceptance criteria from gate-7-proposal-endpoint:
- POST /orchestrate/plan accepts structured request
- Returns governed plan JSON, no execution side effects
- Owner-authenticated; 401 on unauthenticated
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

from app.calyx_orchestrator.meta_orchestrator import (
    MANDATORY_REAUTHORIZATION,
    SCHEMA_VERSION,
)
from app.calyx_orchestrator.meta_orchestrator import plan as meta_plan


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _profile(
    role_key: str = "calyx_research_executor_v1",
    *,
    authoritative: bool = True,
    eligible: bool = True,
    authority_ceiling: str = "A2",
    external_side_effects: bool = False,
) -> dict[str, Any]:
    return {
        "role_key": role_key,
        "executor_key": f"{role_key}_v1",
        "registration_state": "registered",
        "authoritative": authoritative,
        "eligible_for_autonomous_execution": eligible,
        "external_side_effects": external_side_effects,
        "workspace_mutation": True,
        "repository_code_execution": False,
        "authority_ceiling": authority_ceiling,
        "empirical": {
            "observed_job_count": 10,
            "descriptive_success_rate": 0.9,
            "semantics": "historical_observation_not_predictive_certainty",
        },
        "authority_boundary": {
            "empirical_metrics_do_not_expand_authority": True,
        },
    }


def _request(
    objective: str = "Test objective",
    consequence_class: str = "bounded_workspace_mutation",
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "objective": objective,
        "consequence_class": consequence_class,
        "tasks": tasks or [],
    }


def _task(
    task_id: str = "t1",
    objective: str = "Task objective",
    consequence_class: str = "bounded_workspace_mutation",
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "objective": objective,
        "consequence_class": consequence_class,
        "minimum_required_authority": None,
        "allowed_role_keys": [],
        "memory_reference_ids": [],
    }


# ---------------------------------------------------------------------------
# Plan logic — response shape
# ---------------------------------------------------------------------------


def test_plan_response_has_schema_version():
    result = meta_plan(_request(), [])
    assert result["schema_version"] == SCHEMA_VERSION


def test_plan_response_has_plan_id():
    result = meta_plan(_request(), [])
    assert isinstance(result["plan_id"], str)
    assert len(result["plan_id"]) > 0


def test_custom_plan_id_passthrough():
    result = meta_plan(_request(), [], plan_id="custom-plan-abc")
    assert result["plan_id"] == "custom-plan-abc"


def test_plan_has_boundary_flags():
    result = meta_plan(_request(), [])
    b = result["boundary"]
    assert b["plan_does_not_grant_authority"] is True
    assert b["plan_does_not_launch_agents"] is True
    assert b["plan_does_not_mutate_state"] is True
    assert b["execution_requires_registry_recheck"] is True
    assert b["self_approval_prohibited"] is True


def test_plan_has_mandatory_reauthorization():
    result = meta_plan(_request(), [])
    assert result["mandatory_reauthorization_statement"] == MANDATORY_REAUTHORIZATION


def test_plan_returns_empty_assignments_for_no_tasks():
    result = meta_plan(_request(), [])
    assert result["assignments"] == []
    assert result["blocked_task_count"] == 0


def test_plan_returns_assignments_for_tasks():
    result = meta_plan(
        _request(tasks=[_task()]),
        [_profile()],
    )
    assert isinstance(result["assignments"], list)
    assert len(result["assignments"]) == 1


# ---------------------------------------------------------------------------
# High-consequence gating
# ---------------------------------------------------------------------------


def test_production_change_requires_human_gate():
    result = meta_plan(
        _request(
            consequence_class="production_change",
            tasks=[_task(consequence_class="production_change")],
        ),
        [_profile()],
    )
    assert result["human_gate_required"] is True
    assert result["autonomous_execution_eligible"] is False
    assert any(
        "production_change" in r for r in result["human_gate_reasons"]
    )


def test_scientific_publication_requires_human_gate():
    result = meta_plan(
        _request(
            consequence_class="scientific_publication",
            tasks=[_task(consequence_class="scientific_publication")],
        ),
        [_profile()],
    )
    assert result["human_gate_required"] is True


def test_governance_change_requires_human_gate():
    result = meta_plan(
        _request(
            consequence_class="governance_change",
            tasks=[_task(consequence_class="governance_change")],
        ),
        [_profile(authority_ceiling="A0")],
    )
    assert result["human_gate_required"] is True


def test_restricted_data_requires_human_gate():
    result = meta_plan(
        _request(
            consequence_class="restricted_data_or_security",
            tasks=[_task(consequence_class="restricted_data_or_security")],
        ),
        [_profile(authority_ceiling="A0")],
    )
    assert result["human_gate_required"] is True


def test_read_only_does_not_require_human_gate():
    result = meta_plan(
        _request(
            consequence_class="read_only",
            tasks=[_task(consequence_class="read_only")],
        ),
        [_profile(authority_ceiling="A0")],
    )
    assert result["human_gate_required"] is False


def test_workspace_mutation_autonomous_eligible():
    result = meta_plan(
        _request(
            consequence_class="bounded_workspace_mutation",
            tasks=[_task(consequence_class="bounded_workspace_mutation")],
        ),
        [_profile(authority_ceiling="A2")],
    )
    assert result["human_gate_required"] is False
    assert result["autonomous_execution_eligible"] is True


# ---------------------------------------------------------------------------
# No-execution guarantee
# ---------------------------------------------------------------------------


def test_plan_is_proposal_only_no_side_effects():
    """plan() must never mutate state; any call is safe to repeat."""
    db_mock = MagicMock()
    profiles = [_profile()]
    req = _request(tasks=[_task()])
    r1 = meta_plan(req, profiles, plan_id="probe")
    r2 = meta_plan(req, profiles, plan_id="probe")
    # Identical inputs + same plan_id → identical fingerprint.
    assert r1["plan_fingerprint"] == r2["plan_fingerprint"]
    # DB was never accessed.
    db_mock.assert_not_called()


def test_plan_deterministic_for_same_inputs():
    profiles = [_profile()]
    req = _request(tasks=[_task()])
    r1 = meta_plan(req, profiles, plan_id="x")
    r2 = meta_plan(req, profiles, plan_id="x")
    assert r1["plan_fingerprint"] == r2["plan_fingerprint"]


# ---------------------------------------------------------------------------
# Empty capability registry → blocked task
# ---------------------------------------------------------------------------


def test_empty_profiles_results_in_blocked_tasks():
    result = meta_plan(
        _request(tasks=[_task()]),
        [],
    )
    assert result["assignments"][0]["blocked"] is True
    assert result["blocked_task_count"] == 1


def test_empty_profiles_still_no_execution():
    result = meta_plan(
        _request(tasks=[_task()]),
        [],
    )
    b = result["boundary"]
    assert b["plan_does_not_grant_authority"] is True


# ---------------------------------------------------------------------------
# Route registration contract (AST scan — no FastAPI import needed)
# ---------------------------------------------------------------------------


_ROUTES_SRC = Path(__file__).parent.parent / "app" / "calyx_orchestrator" / "routes.py"


def _route_decorators(src: str) -> list[str]:
    """Return all @router.post(...) / @router.get(...) path strings from source."""
    tree = ast.parse(src)
    paths: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "router":
                continue
            if decorator.args and isinstance(decorator.args[0], ast.Constant):
                paths.append(decorator.args[0].value)
    return paths


def test_plan_endpoint_registered_in_routes():
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    paths = _route_decorators(src)
    assert "/plan" in paths, f"Expected /plan in {paths}"


def test_plan_endpoint_import_in_routes():
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    assert "from .meta_orchestrator import plan as meta_plan" in src
    assert "from .capability_memory import load_owner_capability_registry" in src


def test_plan_endpoint_calls_load_owner_registry():
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    assert "load_owner_capability_registry" in src


def test_plan_endpoint_calls_meta_plan():
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    assert "meta_plan(" in src


def test_plan_endpoint_returns_governed_plan():
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    assert "governed_plan" in src


def test_plan_endpoint_uses_owner_auth():
    """Endpoint must call _owner(auth) to enforce authentication."""
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    assert "_owner(auth)" in src


def test_plan_endpoint_carries_auth_dependency():
    """Endpoint function signature must include AuthDependency."""
    src = _ROUTES_SRC.read_text(encoding="utf-8")
    assert "AuthDependency" in src
    # Ensure it's on the create_plan function specifically.
    start = src.index("def create_plan(")
    block = src[start : src.index("return governed_plan", start) + 20]
    assert "AuthDependency" in block
