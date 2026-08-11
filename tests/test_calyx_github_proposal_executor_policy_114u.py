from __future__ import annotations

import pytest

from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationExecutor,
)
from app.calyx_orchestrator.github_proposal_executor_policy import (
    GitHubProposalExecutorPolicy,
    GovernedGitHubProposalExecutorRegistration,
    build_registration,
    github_proposal_executor_status,
)
from tests.test_calyx_github_proposal_mutation_adapter_114u import (
    FakeGitHubTransport,
    MappingPostimages,
    _journal,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "principal:owner"


class ReadyCredential:
    def __init__(self, ready: bool) -> None:
        self.ready = ready
        self.calls = 0

    def credential_ready(self) -> bool:
        self.calls += 1
        return self.ready


def _enabled_environ() -> dict[str, str]:
    return {
        "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
        "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
        "CALYX_GITHUB_PROPOSAL_REPOSITORIES": REPOSITORY,
    }


def test_policy_is_disabled_by_default_even_when_credential_is_ready() -> None:
    status = github_proposal_executor_status({}, credential_ready=True)
    assert status["valid"] is True
    assert status["enabled"] is False
    assert status["ready_for_owner_authorized_draft_pr"] is False
    assert status["external_side_effects"] is False
    assert status["mode"] == "disabled"
    assert "executor_disabled" in status["blockers"]
    assert status["merge_authorized"] is False
    assert status["deployment_authorized"] is False
    assert status["publication_authorized"] is False
    assert status["production_graph_mutation_authorized"] is False


def test_enabled_policy_requires_owner_and_repository_allowlist() -> None:
    with pytest.raises(ValueError, match="OWNER_REQUIRED"):
        GitHubProposalExecutorPolicy.from_environ(
            {"CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true"}
        )
    with pytest.raises(ValueError, match="REPOSITORIES_REQUIRED"):
        GitHubProposalExecutorPolicy.from_environ(
            {
                "CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true",
                "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER": OWNER,
            }
        )


def test_repository_allowlist_is_normalized_without_widening() -> None:
    policy = GitHubProposalExecutorPolicy.from_environ(
        {
            **_enabled_environ(),
            "CALYX_GITHUB_PROPOSAL_REPOSITORIES": (
                f" {REPOSITORY}, {REPOSITORY},jsp1440/orchid-continuum-frontend "
            ),
        }
    )
    assert policy.repositories == (
        REPOSITORY,
        "jsp1440/orchid-continuum-frontend",
    )
    with pytest.raises(ValueError, match="REPOSITORIES_INVALID"):
        GitHubProposalExecutorPolicy.from_environ(
            {
                **_enabled_environ(),
                "CALYX_GITHUB_PROPOSAL_REPOSITORIES": "not-a-repository",
            }
        )


def test_registration_fails_closed_until_all_four_gates_are_ready() -> None:
    disabled = GovernedGitHubProposalExecutorRegistration(
        policy=GitHubProposalExecutorPolicy(), credential_ready=True
    )
    with pytest.raises(PermissionError, match="EXECUTOR_DISABLED"):
        disabled.require_ready(owner=OWNER, repository=REPOSITORY)

    policy = GitHubProposalExecutorPolicy.from_environ(_enabled_environ())
    registration = GovernedGitHubProposalExecutorRegistration(
        policy=policy, credential_ready=False
    )
    with pytest.raises(PermissionError, match="OWNER_MISMATCH"):
        registration.require_ready(owner="principal:other", repository=REPOSITORY)
    with pytest.raises(PermissionError, match="REPOSITORY_NOT_ALLOWED"):
        registration.require_ready(owner=OWNER, repository="jsp1440/other")
    with pytest.raises(PermissionError, match="CREDENTIAL_NOT_READY"):
        registration.require_ready(owner=OWNER, repository=REPOSITORY)


def test_build_registration_checks_readiness_without_reading_a_secret() -> None:
    readiness = ReadyCredential(True)
    registration = build_registration(
        environ=_enabled_environ(), credential_readiness=readiness
    )
    assert readiness.calls == 1
    status = registration.status()
    assert status["ready_for_owner_authorized_draft_pr"] is True
    assert status["credential_ready"] is True
    assert "credential" not in registration.__dict__


def test_ready_registration_constructs_only_the_bounded_proposal_executor() -> None:
    journal = _journal()
    registration = GovernedGitHubProposalExecutorRegistration(
        policy=GitHubProposalExecutorPolicy.from_environ(_enabled_environ()),
        credential_ready=True,
    )
    executor = registration.build_executor(
        owner=OWNER,
        repository=REPOSITORY,
        transport=FakeGitHubTransport(),
        postimages=MappingPostimages(),
        evidence=journal,
    )
    assert isinstance(executor, GitProposalMutationExecutor)
    status = registration.status()
    assert status["branch_namespace"] == "autonomy/proposal/"
    assert status["draft_pull_request_only"] is True
    assert status["force_push_authorized"] is False
    assert status["branch_deletion_authorized"] is False
    assert status["merge_authorized"] is False
    assert status["automatic_merge_authorized"] is False
    assert status["credential_disclosure_authorized"] is False
    assert status["spending_authorized"] is False


def test_invalid_environment_status_is_truthful_and_fail_closed() -> None:
    status = github_proposal_executor_status(
        {"CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED": "true"},
        credential_ready=True,
    )
    assert status["valid"] is False
    assert status["enabled"] is False
    assert status["ready_for_owner_authorized_draft_pr"] is False
    assert status["external_side_effects"] is False
    assert status["error"] == "CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER_REQUIRED"
