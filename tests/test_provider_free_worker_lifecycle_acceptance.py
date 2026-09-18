"""Acceptance proof for the provider-free coding worker lifecycle.

Uses the production executor and provider-free adapter with in-memory gateways.
No network/provider API is reachable from this test.
"""

from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.github_coding_executor import (
    GITHUB_CODING_ROLE,
    GitHubCodingAgentExecutor,
    RepositorySnapshot,
)
from app.calyx_orchestrator.provider_free_coding_adapter import (
    DeterministicWorkerReceipt,
    ProviderFreeCodingAdapter,
)


class Inspector:
    def inspect(self, *, repository, objective, mission_id):
        return RepositorySnapshot(
            repository=repository,
            base_ref="oc-autonomous-integration",
            base_sha="a" * 40,
            related_issue_numbers=(660,),
        )


def assignment():
    return GovernedAssignment(
        assignment_id="assignment-660",
        program_id="program-660",
        job_key="mission-660",
        role_key=GITHUB_CODING_ROLE,
        objective="Implement bounded prepared issue 660",
        inputs={
            "job": {
                "repository": "orchid-continuum-frontend",
                "mission_id": "mission-660",
                "objective": "Implement bounded prepared issue 660",
                "acceptance_criteria": ["exact-head tests pass"],
                "validation_commands": ["npm test"],
                "budget_class": "TINY",
                "mutating_intent": True,
                "executor_class": "deterministic-local",
            },
            "governance": {
                "external_execution_authorized": True,
                "repository_code_execution_authorized": True,
                "automatic_merge_authorized": False,
                "deployment_authorized": False,
                "publication_authorized": False,
                "production_graph_mutation_authorized": False,
            },
        },
    )


def test_provider_free_worker_executes_once_with_draft_pr_and_exact_head_evidence():
    calls = []

    def runner(request):
        calls.append(request)
        return DeterministicWorkerReceipt(
            branch="oc-auto-660",
            issue_number=660,
            pull_request_number=1491,
            pull_request_url="https://github.com/jsp1440/orchid-continuum-frontend/pull/1491",
            head_sha="b" * 40,
            validation_evidence=("npm-test:passed",),
        )

    executor = GitHubCodingAgentExecutor(
        inspector=Inspector(),
        provider=ProviderFreeCodingAdapter(runner),
    )
    receipt = executor.execute(assignment())

    assert len(calls) == 1
    assert receipt.output["status"] == "dispatched"
    assert receipt.output["provider"] == "provider-free"
    assert receipt.output["executor_class"] == "deterministic-local"
    assert receipt.output["draft"] is True
    assert receipt.output["head_sha"] == "b" * 40
    assert receipt.output["automatic_merge"] is False
    assert receipt.output["automatic_deployment"] is False
    assert receipt.output["production_mutation"] is False
    assert receipt.output["publication"] is False
    assert "npm-test:passed" in receipt.output["validation_evidence"]


def test_worker_has_no_paid_provider_path():
    adapter = ProviderFreeCodingAdapter(
        lambda _: DeterministicWorkerReceipt(
            branch="oc-auto-660",
            issue_number=660,
            pull_request_number=1491,
            pull_request_url="https://github.com/jsp1440/orchid-continuum-frontend/pull/1491",
            head_sha="b" * 40,
        )
    )
    assert adapter.provider_name == "provider-free"
    assert adapter.executor_class == "deterministic-local"
    assert not hasattr(adapter, "api_key")
    assert not hasattr(adapter, "client")
