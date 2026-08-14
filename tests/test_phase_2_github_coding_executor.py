from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.github_coding_executor import (
    BudgetClass,
    ConvergenceClass,
    DispatchRequest,
    DispatchResult,
    GitHubCodingAgentExecutor,
    RepositorySnapshot,
    classify_convergence,
)


@dataclass
class Inspector:
    snapshot: RepositorySnapshot
    calls: int = 0
    last_mission_id: str | None = None

    def inspect(self, *, repository: str, objective: str, mission_id: str) -> RepositorySnapshot:
        self.calls += 1
        self.last_mission_id = mission_id
        return self.snapshot


@dataclass
class Provider:
    result: DispatchResult
    provider_name: str = "test-provider"
    executor_class: str = "test"
    calls: int = 0
    request: DispatchRequest | None = None

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        self.calls += 1
        self.request = request
        return self.result


def assignment(job: dict) -> GovernedAssignment:
    return GovernedAssignment(
        assignment_id="assignment-1",
        program_id="program-1",
        job_key="MISSION-1",
        role_key="github_coding_agent",
        objective="Implement the mission",
        inputs={"job": job},
        evidence_uris=("issue:973",),
    )


def snapshot(**kwargs) -> RepositorySnapshot:
    defaults = {
        "repository": "jsp1440/orchid-calyx-backend",
        "base_ref": "main",
        "base_sha": "a" * 40,
    }
    defaults.update(kwargs)
    return RepositorySnapshot(**defaults)


def result(**kwargs) -> DispatchResult:
    defaults = {
        "provider": "copilot",
        "executor_class": "cloud_coding_agent",
        "repository": "jsp1440/orchid-calyx-backend",
        "base_sha": "a" * 40,
        "branch": "agent/mission-1",
        "issue_number": 973,
        "pull_request_number": 1000,
        "pull_request_url": "https://github.com/jsp1440/orchid-calyx-backend/pull/1000",
        "draft": True,
    }
    defaults.update(kwargs)
    return DispatchResult(**defaults)


def job(**kwargs) -> dict:
    defaults = {
        "mission_id": "MISSION-1",
        "repository": "jsp1440/orchid-calyx-backend",
        "objective": "Implement provider-neutral GitHub agent dispatch",
        "acceptance_criteria": ["no duplicate PR"],
        "validation_commands": ["pytest -q tests/test_phase_2_github_coding_executor.py"],
        "budget_class": "NORMAL",
    }
    defaults.update(kwargs)
    return defaults


def test_convergence_precedence() -> None:
    assert classify_convergence(snapshot(implementation_complete=True)) == ConvergenceClass.ALREADY_DONE
    assert classify_convergence(snapshot(convergence_pr_numbers=(7, 8))) == ConvergenceClass.CONVERGE
    assert classify_convergence(snapshot(continuation_pr_numbers=(7,))) == ConvergenceClass.CONTINUE
    assert classify_convergence(snapshot(superseded_pr_numbers=(7,))) == ConvergenceClass.SUPERSEDE
    assert classify_convergence(snapshot()) == ConvergenceClass.NEW


def test_already_done_never_dispatches_or_creates_branch() -> None:
    inspector = Inspector(snapshot(implementation_complete=True, overlapping_pr_numbers=(900,)))
    provider = Provider(result())
    receipt = GitHubCodingAgentExecutor(inspector=inspector, provider=provider).execute(assignment(job()))
    assert inspector.last_mission_id == "MISSION-1"
    assert receipt.output["convergence_class"] == "ALREADY_DONE"
    assert receipt.output["branch_created"] is False
    assert receipt.output["pull_request_created"] is False
    assert provider.calls == 0


def test_overlapping_prs_are_bound_into_dispatch_request_and_receipt() -> None:
    inspector = Inspector(
        snapshot(
            overlapping_pr_numbers=(900, 901),
            convergence_pr_numbers=(900, 901),
            related_issue_numbers=(973,),
        )
    )
    provider = Provider(result())
    receipt = GitHubCodingAgentExecutor(inspector=inspector, provider=provider).execute(assignment(job()))
    assert provider.calls == 1
    assert provider.request is not None
    assert provider.request.convergence_class == ConvergenceClass.CONVERGE
    assert provider.request.overlapping_pr_numbers == (900, 901)
    assert provider.request.budget_class == BudgetClass.NORMAL
    assert receipt.output["overlapping_pr_numbers"] == [900, 901]
    assert receipt.output["draft"] is True
    assert receipt.output["automatic_merge"] is False


def test_retry_budget_stops_before_inspection_or_dispatch() -> None:
    inspector = Inspector(snapshot())
    provider = Provider(result())
    receipt = GitHubCodingAgentExecutor(inspector=inspector, provider=provider).execute(
        assignment(job(same_failure_retry_count=3))
    )
    assert receipt.blocker_code == "RETRY_BUDGET_EXHAUSTED"
    assert inspector.calls == 0
    assert provider.calls == 0
    assert receipt.output["escalation"] == "integrator_or_reviewer"


def test_non_draft_provider_result_fails_closed() -> None:
    inspector = Inspector(snapshot())
    provider = Provider(result(draft=False))
    with pytest.raises(PermissionError, match="GITHUB_CODING_NON_DRAFT_PR_PROHIBITED"):
        GitHubCodingAgentExecutor(inspector=inspector, provider=provider).execute(assignment(job()))


def test_dispatch_identity_mismatch_fails_closed() -> None:
    inspector = Inspector(snapshot())
    provider = Provider(result(base_sha="b" * 40))
    with pytest.raises(PermissionError, match="GITHUB_CODING_DISPATCH_IDENTITY_MISMATCH"):
        GitHubCodingAgentExecutor(inspector=inspector, provider=provider).execute(assignment(job()))
