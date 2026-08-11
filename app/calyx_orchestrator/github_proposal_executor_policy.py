from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from .git_proposal_mutation_executor import GitProposalMutationExecutor
from .github_proposal_mutation_adapter import (
    GitHubProposalMutationAdapter,
    GitHubTransport,
    ProposalEvidenceResolver,
    ProposalPostimageResolver,
)

_ENABLED = frozenset({"1", "true", "yes", "on"})


def _enabled(value: object) -> bool:
    return str(value or "").strip().casefold() in _ENABLED


def _repositories(value: object) -> tuple[str, ...]:
    raw = str(value or "")
    repositories = tuple(
        dict.fromkeys(item.strip() for item in raw.split(",") if item.strip())
    )
    for repository in repositories:
        parts = repository.split("/")
        if len(parts) != 2 or not all(parts):
            raise ValueError("CALYX_GITHUB_PROPOSAL_REPOSITORIES_INVALID")
    return repositories


class CredentialReadiness(Protocol):
    """Secret-preserving readiness boundary; never exposes credential material."""

    def credential_ready(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class GitHubProposalExecutorPolicy:
    enabled: bool = False
    owner: str = ""
    repositories: tuple[str, ...] = ()

    @classmethod
    def from_environ(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> GitHubProposalExecutorPolicy:
        source = os.environ if environ is None else environ
        return cls(
            enabled=_enabled(source.get("CALYX_GITHUB_PROPOSAL_EXECUTOR_ENABLED")),
            owner=str(source.get("CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER", "")).strip(),
            repositories=_repositories(
                source.get("CALYX_GITHUB_PROPOSAL_REPOSITORIES", "")
            ),
        ).validated()

    def validated(self) -> GitHubProposalExecutorPolicy:
        if self.enabled and not self.owner:
            raise ValueError("CALYX_GITHUB_PROPOSAL_EXECUTOR_OWNER_REQUIRED")
        if self.enabled and not self.repositories:
            raise ValueError("CALYX_GITHUB_PROPOSAL_REPOSITORIES_REQUIRED")
        return self

    def status(self, *, credential_ready: bool = False) -> dict[str, object]:
        ready = (
            self.enabled
            and bool(self.owner)
            and bool(self.repositories)
            and credential_ready
        )
        blockers: list[str] = []
        if not self.enabled:
            blockers.append("executor_disabled")
        if self.enabled and not self.owner:
            blockers.append("owner_not_configured")
        if self.enabled and not self.repositories:
            blockers.append("repository_allowlist_not_configured")
        if self.enabled and not credential_ready:
            blockers.append("credential_not_ready")
        return {
            "enabled": self.enabled,
            "owner_configured": bool(self.owner),
            "allowed_repositories": list(self.repositories),
            "credential_ready": credential_ready,
            "ready_for_owner_authorized_draft_pr": ready,
            "mode": "owner_authorized_draft_pr_only" if ready else "disabled",
            "blockers": blockers,
            "external_side_effects": ready,
            "branch_namespace": "autonomy/proposal/",
            "draft_pull_request_only": True,
            "force_push_authorized": False,
            "branch_deletion_authorized": False,
            "merge_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
            "credential_disclosure_authorized": False,
            "spending_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class GovernedGitHubProposalExecutorRegistration:
    """Explicit registration object kept separate from internal executor registry."""

    policy: GitHubProposalExecutorPolicy
    credential_ready: bool

    def status(self) -> dict[str, object]:
        return self.policy.status(credential_ready=self.credential_ready)

    def require_ready(self, *, owner: str, repository: str) -> None:
        if not self.policy.enabled:
            raise PermissionError("GITHUB_PROPOSAL_EXECUTOR_DISABLED")
        if owner != self.policy.owner:
            raise PermissionError("GITHUB_PROPOSAL_EXECUTOR_OWNER_MISMATCH")
        if repository not in self.policy.repositories:
            raise PermissionError("GITHUB_PROPOSAL_EXECUTOR_REPOSITORY_NOT_ALLOWED")
        if not self.credential_ready:
            raise PermissionError("GITHUB_PROPOSAL_EXECUTOR_CREDENTIAL_NOT_READY")

    def build_executor(
        self,
        *,
        owner: str,
        repository: str,
        transport: GitHubTransport,
        postimages: ProposalPostimageResolver,
        evidence: ProposalEvidenceResolver,
    ) -> GitProposalMutationExecutor:
        self.require_ready(owner=owner, repository=repository)
        adapter = GitHubProposalMutationAdapter(
            transport=transport,
            postimages=postimages,
            evidence=evidence,
            repository_allowlist=self.policy.repositories,
        )
        return GitProposalMutationExecutor(
            adapter=adapter,
            repository_allowlist=self.policy.repositories,
            journal=evidence,
        )


def github_proposal_executor_status(
    environ: Mapping[str, str] | None = None,
    *,
    credential_ready: bool = False,
) -> dict[str, object]:
    try:
        policy = GitHubProposalExecutorPolicy.from_environ(environ)
    except ValueError as exc:
        return {
            "valid": False,
            "error": str(exc),
            **GitHubProposalExecutorPolicy().status(credential_ready=False),
        }
    return {
        "valid": True,
        "error": None,
        **policy.status(credential_ready=credential_ready),
    }


def build_registration(
    *,
    environ: Mapping[str, str] | None = None,
    credential_readiness: CredentialReadiness | None = None,
) -> GovernedGitHubProposalExecutorRegistration:
    policy = GitHubProposalExecutorPolicy.from_environ(environ)
    credential_ready = (
        False
        if credential_readiness is None
        else bool(credential_readiness.credential_ready())
    )
    return GovernedGitHubProposalExecutorRegistration(
        policy=policy,
        credential_ready=credential_ready,
    )
