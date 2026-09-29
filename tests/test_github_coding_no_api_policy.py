from types import SimpleNamespace

import pytest

from app.calyx_orchestrator.github_agent_dispatch_cycle import GitHubCodingRuntimePolicy
from app.calyx_orchestrator.github_coding_executor import BudgetClass


def assignment(executor_class: str):
    return SimpleNamespace(
        inputs={
            "job": {
                "repository": "orchid-calyx-backend",
                "mutating_intent": True,
                "budget_class": "TINY",
                "executor_class": executor_class,
            }
        }
    )


def policy(**kw):
    base = {
        "enabled": True,
        "owner_allowlist": frozenset({"jsp1440"}),
        "repository_allowlist": frozenset({"orchid-calyx-backend"}),
        "max_budget_class": BudgetClass.TINY,
        "no_api_mode": True,
        "provider_free_executors": frozenset({"deterministic-local"}),
    }
    base.update(kw)
    return GitHubCodingRuntimePolicy(**base)


def test_no_api_mode_rejects_unapproved_provider_executor():
    with pytest.raises(PermissionError, match="GITHUB_CODING_PROVIDER_PROHIBITED_NO_API"):
        policy().validate_assignment(assignment("openai"))


def test_no_api_mode_rejects_missing_executor_identity():
    with pytest.raises(PermissionError, match="GITHUB_CODING_PROVIDER_PROHIBITED_NO_API"):
        policy().validate_assignment(assignment(""))


def test_explicit_provider_free_executor_is_admitted():
    budget = policy().validate_assignment(assignment("deterministic-local"))
    assert budget == BudgetClass.TINY


def test_disabling_no_api_does_not_happen_implicitly():
    assert policy().no_api_mode is True
