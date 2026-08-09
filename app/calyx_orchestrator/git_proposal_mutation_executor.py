from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .git_mutation_authorization import (
    GitMutationAuthorizationGate,
    GitMutationAuthorizationRequest,
)
from .git_proposal_execution_plan import (
    ACTION_ORDER,
    GitProposalExecutionPlan,
    GitProposalExecutionPlanner,
    GitProposalPlanOperation,
)
from .proposal_authorization_store import DurableProposalAuthorizationStore
from .sandbox_supervisor_evidence import canonical_sha256

SCHEMA = "calyx-git-proposal-mutation-receipt-v1"
ALLOWED_BRANCH_PREFIX = "autonomy/proposal/"
ALLOWED_ACTIONS = frozenset(ACTION_ORDER)
FINAL_ACTION = "open_pull_request"


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


class GitProposalMutationAdapter(Protocol):
    """Narrow proposal-only mutation capability injected by a trusted boundary."""

    def apply_proposal_operation(
        self,
        *,
        plan_digest: str,
        operation: GitProposalPlanOperation,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class GitProposalOperationEvidence:
    action: str
    status: str
    evidence_digest: str
    payload: Mapping[str, Any]

    def snapshot(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "status": self.status,
            "evidence_digest": self.evidence_digest,
            "payload": dict(self.payload),
        }


@dataclass(frozen=True, slots=True)
class GitProposalMutationReceipt:
    plan_digest: str
    repository: str
    proposed_branch: str
    base_commit_sha: str
    status: str
    completed_actions: tuple[str, ...]
    operation_evidence: tuple[GitProposalOperationEvidence, ...]
    failure_code: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "plan_digest": self.plan_digest,
            "repository": self.repository,
            "proposed_branch": self.proposed_branch,
            "base_commit_sha": self.base_commit_sha,
            "status": self.status,
            "completed_actions": list(self.completed_actions),
            "operation_evidence": [item.snapshot() for item in self.operation_evidence],
            "failure_code": self.failure_code,
            "proposal_mutation_scope_only": True,
            "merge_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
        }

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256(self.payload())

    def snapshot(self) -> dict[str, Any]:
        return {**self.payload(), "receipt_digest": self.receipt_digest}


class GitProposalMutationJournal(Protocol):
    """Persistence capability injected separately from the mutation adapter."""

    def record(
        self,
        receipt: GitProposalMutationReceipt,
        *,
        event_index: int,
    ) -> GitProposalMutationReceipt: ...


class GitProposalMutationError(RuntimeError):
    """Raised after a mutation attempt fails; carries exact partial-side-effect evidence."""

    def __init__(self, code: str, receipt: GitProposalMutationReceipt) -> None:
        super().__init__(code)
        self.code = code
        self.receipt = receipt


class GitProposalMutationExecutor:
    """Execute only an exact, freshly reverified BUILD-BRAIN-114R proposal plan."""

    def __init__(
        self,
        *,
        adapter: GitProposalMutationAdapter,
        repository_allowlist: Sequence[str],
        journal: GitProposalMutationJournal | None = None,
    ) -> None:
        normalized = frozenset(
            item.strip() for item in repository_allowlist if item.strip()
        )
        if not normalized:
            raise ValueError("GIT_PROPOSAL_EXECUTOR_REPOSITORY_ALLOWLIST_REQUIRED")
        self._adapter = adapter
        self._repository_allowlist = normalized
        self._journal = journal

    def execute(
        self,
        *,
        plan: GitProposalExecutionPlan,
        manifest_snapshot: Mapping[str, Any],
        review_store: DurableProposalAuthorizationStore,
        authorization_gate: GitMutationAuthorizationGate,
        request: GitMutationAuthorizationRequest,
        grant_mapping: Mapping[str, Any],
        now: datetime | None = None,
    ) -> GitProposalMutationReceipt:
        verified_plan = GitProposalExecutionPlanner.build(
            manifest_snapshot=manifest_snapshot,
            review_store=review_store,
            authorization_gate=authorization_gate,
            request=request,
            grant_mapping=grant_mapping,
            now=now,
        )
        if verified_plan.snapshot() != plan.snapshot():
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_PLAN_MISMATCH")
        if plan.repository not in self._repository_allowlist:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_REPOSITORY_NOT_ALLOWED")
        if not plan.proposed_branch.startswith(ALLOWED_BRANCH_PREFIX):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_BRANCH_NOT_ALLOWED")
        if not _is_git_sha(plan.base_commit_sha):
            raise ValueError("GIT_PROPOSAL_EXECUTOR_BASE_COMMIT_INVALID")

        actions = tuple(operation.action for operation in plan.operations)
        if not actions or any(action not in ALLOWED_ACTIONS for action in actions):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_ACTION_NOT_ALLOWED")
        canonical = tuple(action for action in ACTION_ORDER if action in actions)
        if actions != canonical or len(actions) != len(set(actions)):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_ACTION_ORDER_INVALID")

        evidence: list[GitProposalOperationEvidence] = []
        completed: list[str] = []
        plan_digest = plan.plan_digest
        expected_commit_sha: str | None = None

        for operation in plan.operations:
            try:
                raw = self._adapter.apply_proposal_operation(
                    plan_digest=plan_digest,
                    operation=operation,
                )
                item = self._verify_operation_evidence(
                    plan=plan,
                    operation=operation,
                    raw=raw,
                    expected_commit_sha=expected_commit_sha,
                )
            except Exception as exc:
                code = getattr(exc, "code", None) or exc.__class__.__name__
                receipt = self._receipt(
                    plan=plan,
                    status="partial_failure" if completed else "failed",
                    completed=completed,
                    evidence=evidence,
                    failure_code=str(code),
                )
                self._record(receipt, event_index=len(completed) + 1)
                raise GitProposalMutationError(str(code), receipt) from exc

            evidence.append(item)
            completed.append(operation.action)
            if operation.action == "create_commit":
                expected_commit_sha = str(item.payload["commit_sha"]).lower()

            progress = self._receipt(
                plan=plan,
                status="in_progress",
                completed=completed,
                evidence=evidence,
                failure_code=None,
            )
            self._record(progress, event_index=len(completed))

        status = (
            "completed"
            if completed and completed[-1] == FINAL_ACTION
            else "completed_subset"
        )
        receipt = self._receipt(
            plan=plan,
            status=status,
            completed=completed,
            evidence=evidence,
            failure_code=None,
        )
        self._record(receipt, event_index=len(completed) + 1)
        return receipt

    def _record(self, receipt: GitProposalMutationReceipt, *, event_index: int) -> None:
        if self._journal is None:
            return
        persisted = self._journal.record(receipt, event_index=event_index)
        if persisted.snapshot() != receipt.snapshot():
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_JOURNAL_MISMATCH")

    @staticmethod
    def _receipt(
        *,
        plan: GitProposalExecutionPlan,
        status: str,
        completed: Sequence[str],
        evidence: Sequence[GitProposalOperationEvidence],
        failure_code: str | None,
    ) -> GitProposalMutationReceipt:
        return GitProposalMutationReceipt(
            plan_digest=plan.plan_digest,
            repository=plan.repository,
            proposed_branch=plan.proposed_branch,
            base_commit_sha=plan.base_commit_sha,
            status=status,
            completed_actions=tuple(completed),
            operation_evidence=tuple(evidence),
            failure_code=failure_code,
        )

    @staticmethod
    def _verify_operation_evidence(
        *,
        plan: GitProposalExecutionPlan,
        operation: GitProposalPlanOperation,
        raw: Mapping[str, Any],
        expected_commit_sha: str | None,
    ) -> GitProposalOperationEvidence:
        if not isinstance(raw, Mapping):
            raise TypeError("GIT_PROPOSAL_EXECUTOR_EVIDENCE_INVALID")
        payload = dict(raw)
        action = str(payload.get("action") or "").strip()
        status = str(payload.get("status") or "").strip()
        repository = str(payload.get("repository") or "").strip()
        branch = str(payload.get("branch") or "").strip()
        if action != operation.action:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_EVIDENCE_ACTION_MISMATCH")
        if status not in {"created", "already_exists_exact"}:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_EVIDENCE_STATUS_INVALID")
        if repository != plan.repository or branch != plan.proposed_branch:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_EVIDENCE_TARGET_MISMATCH")

        if action == "create_branch":
            base = str(payload.get("base_commit_sha") or "").strip().lower()
            if base != plan.base_commit_sha:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_BRANCH_BASE_MISMATCH")
        elif action == "create_commit":
            parent = str(payload.get("parent_commit_sha") or "").strip().lower()
            commit = str(payload.get("commit_sha") or "").strip().lower()
            returned_changes = payload.get("change_hashes")
            expected_changes = [
                {"path": path, "after_sha256": digest}
                for path, digest in plan.change_hashes
            ]
            if parent != plan.base_commit_sha or not _is_git_sha(commit):
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_COMMIT_EVIDENCE_INVALID")
            if returned_changes != expected_changes:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_COMMIT_POSTIMAGE_MISMATCH")
        elif action == "push_branch":
            commit = str(payload.get("commit_sha") or "").strip().lower()
            if not _is_git_sha(commit):
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PUSH_COMMIT_INVALID")
            if expected_commit_sha is not None and commit != expected_commit_sha:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PUSH_COMMIT_MISMATCH")
        elif action == "open_pull_request":
            head = str(payload.get("head_branch") or "").strip()
            base = str(payload.get("base_commit_sha") or "").strip().lower()
            head_commit = str(payload.get("head_commit_sha") or "").strip().lower()
            pr_number = payload.get("pull_request_number")
            if head != plan.proposed_branch or base != plan.base_commit_sha:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PR_TARGET_MISMATCH")
            if expected_commit_sha is not None and head_commit != expected_commit_sha:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PR_COMMIT_MISMATCH")
            if not isinstance(pr_number, int) or pr_number <= 0:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PR_NUMBER_INVALID")
        else:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_ACTION_NOT_ALLOWED")

        digest = canonical_sha256(payload)
        return GitProposalOperationEvidence(
            action=action,
            status=status,
            evidence_digest=digest,
            payload=payload,
        )
