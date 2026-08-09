from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .git_mutation_authorization import (
    GitMutationAuthorizationGate,
    GitMutationAuthorizationRequest,
)
from .proposal_authorization_store import DurableProposalAuthorizationStore
from .sandbox_supervisor_evidence import canonical_sha256

SCHEMA = "calyx-git-proposal-execution-plan-v2"
ACTION_ORDER = (
    "create_branch",
    "create_commit",
    "push_branch",
    "open_pull_request",
)


@dataclass(frozen=True, slots=True)
class GitProposalPlanOperation:
    action: str
    parameters: Mapping[str, Any]

    def payload(self) -> dict[str, Any]:
        return {"action": self.action, "parameters": copy.deepcopy(dict(self.parameters))}


@dataclass(frozen=True, slots=True)
class GitProposalExecutionPlan:
    manifest_digest: str
    patch_program_job_id: str
    authorization_request_digest: str
    repository: str
    base_commit_sha: str
    base_ref: str
    proposed_branch: str
    change_hashes: tuple[tuple[str, str], ...]
    validation_receipt_digests: tuple[str, ...]
    review_authorization_digests: tuple[str, ...]
    owner_approved_by: str
    owner_grant_expires_at: str
    owner_grant_signature_digest: str
    commit_title: str
    pr_title: str
    summary: str
    operations: tuple[GitProposalPlanOperation, ...]

    def payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "manifest_digest": self.manifest_digest,
            "patch_program_job_id": self.patch_program_job_id,
            "authorization_request_digest": self.authorization_request_digest,
            "repository": self.repository,
            "base_commit_sha": self.base_commit_sha,
            "base_ref": self.base_ref,
            "proposed_branch": self.proposed_branch,
            "change_hashes": [
                {"path": path, "after_sha256": digest}
                for path, digest in self.change_hashes
            ],
            "validation_receipt_digests": list(self.validation_receipt_digests),
            "review_authorization_digests": list(self.review_authorization_digests),
            "owner_approved_by": self.owner_approved_by,
            "owner_grant_expires_at": self.owner_grant_expires_at,
            "owner_grant_signature_digest": self.owner_grant_signature_digest,
            "commit_title": self.commit_title,
            "pr_title": self.pr_title,
            "summary": self.summary,
            "operations": [operation.payload() for operation in self.operations],
            "owner_grant_verified": True,
            "plan_only": True,
            "git_mutation_performed": False,
            "branch_created": False,
            "commit_created": False,
            "push_performed": False,
            "pull_request_created": False,
            "merge_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @property
    def plan_digest(self) -> str:
        return canonical_sha256(self.payload())

    def snapshot(self) -> dict[str, Any]:
        return {**self.payload(), "plan_digest": self.plan_digest}


class GitProposalExecutionPlanner:
    """Compile exact authorized proposal evidence into a deterministic plan only."""

    @staticmethod
    def build(
        *,
        manifest_snapshot: Mapping[str, Any],
        review_store: DurableProposalAuthorizationStore,
        authorization_gate: GitMutationAuthorizationGate,
        request: GitMutationAuthorizationRequest,
        grant_mapping: Mapping[str, Any],
        now: datetime | None = None,
    ) -> GitProposalExecutionPlan:
        expected_request = authorization_gate.build_request(
            manifest_snapshot,
            review_store=review_store,
            actions=request.actions,
            base_ref=request.base_ref,
            expires_at=request.expires_at,
            now=now,
        )
        if expected_request.snapshot() != request.snapshot():
            raise PermissionError("GIT_PROPOSAL_PLAN_AUTHORIZATION_REQUEST_MISMATCH")

        verified_grant = authorization_gate.verify_grant(request, grant_mapping)

        commit_title = str(manifest_snapshot.get("commit_title") or "").strip()
        pr_title = str(manifest_snapshot.get("pr_title") or "").strip()
        summary = str(manifest_snapshot.get("summary") or "").strip()
        if not commit_title or not pr_title or not summary:
            raise ValueError("GIT_PROPOSAL_PLAN_MANIFEST_TEXT_REQUIRED")

        GitProposalExecutionPlanner._require_dependency_closed_actions(request.actions)
        operations = tuple(
            GitProposalExecutionPlanner._operation(
                action,
                request=request,
                commit_title=commit_title,
                pr_title=pr_title,
                summary=summary,
            )
            for action in ACTION_ORDER
            if action in request.actions
        )
        if len(operations) != len(request.actions):
            raise PermissionError("GIT_PROPOSAL_PLAN_ACTION_SET_INVALID")

        return GitProposalExecutionPlan(
            manifest_digest=request.manifest_digest,
            patch_program_job_id=request.patch_program_job_id,
            authorization_request_digest=request.request_digest,
            repository=request.repository,
            base_commit_sha=request.base_commit_sha,
            base_ref=request.base_ref,
            proposed_branch=request.proposed_branch,
            change_hashes=request.change_hashes,
            validation_receipt_digests=request.validation_receipt_digests,
            review_authorization_digests=request.review_authorization_digests,
            owner_approved_by=verified_grant.approved_by,
            owner_grant_expires_at=verified_grant.expires_at,
            owner_grant_signature_digest=canonical_sha256(
                {"signature": verified_grant.signature}
            ),
            commit_title=commit_title,
            pr_title=pr_title,
            summary=summary,
            operations=operations,
        )

    @staticmethod
    def _require_dependency_closed_actions(actions: tuple[str, ...]) -> None:
        requested = set(actions)
        for action in actions:
            try:
                position = ACTION_ORDER.index(action)
            except ValueError as exc:
                raise PermissionError("GIT_PROPOSAL_PLAN_ACTION_SET_INVALID") from exc
            prerequisites = set(ACTION_ORDER[: position + 1])
            if not prerequisites.issubset(requested):
                raise PermissionError("GIT_PROPOSAL_PLAN_ACTION_PREREQUISITE_MISSING")

    @staticmethod
    def _operation(
        action: str,
        *,
        request: GitMutationAuthorizationRequest,
        commit_title: str,
        pr_title: str,
        summary: str,
    ) -> GitProposalPlanOperation:
        if action == "create_branch":
            parameters: dict[str, Any] = {
                "repository": request.repository,
                "base_commit_sha": request.base_commit_sha,
                "branch": request.proposed_branch,
            }
        elif action == "create_commit":
            parameters = {
                "repository": request.repository,
                "branch": request.proposed_branch,
                "base_commit_sha": request.base_commit_sha,
                "patch_program_job_id": request.patch_program_job_id,
                "change_hashes": [
                    {"path": path, "after_sha256": digest}
                    for path, digest in request.change_hashes
                ],
                "commit_title": commit_title,
            }
        elif action == "push_branch":
            parameters = {
                "repository": request.repository,
                "branch": request.proposed_branch,
            }
        elif action == "open_pull_request":
            parameters = {
                "repository": request.repository,
                "base_ref": request.base_ref,
                "base_commit_sha": request.base_commit_sha,
                "head_branch": request.proposed_branch,
                "pr_title": pr_title,
                "summary": summary,
            }
        else:
            raise PermissionError("GIT_PROPOSAL_PLAN_ACTION_NOT_ALLOWED")
        return GitProposalPlanOperation(action=action, parameters=parameters)
