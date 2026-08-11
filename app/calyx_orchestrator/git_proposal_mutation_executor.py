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

SCHEMA = "calyx-git-proposal-mutation-receipt-v3"
ALLOWED_BRANCH_PREFIX = "autonomy/proposal/"
ALLOWED_ACTIONS = frozenset(ACTION_ORDER)
FINAL_ACTION = "open_pull_request"
FINAL_STATUSES = frozenset({"completed", "completed_subset"})


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _require_dependency_closed_prefix(actions: Sequence[str]) -> None:
    normalized = tuple(actions)
    if not normalized or normalized != ACTION_ORDER[: len(normalized)]:
        raise PermissionError("GIT_PROPOSAL_EXECUTOR_ACTION_DEPENDENCY_INVALID")


def _failure_code(exc: Exception) -> str:
    structured = getattr(exc, "code", None)
    if structured:
        return str(structured)
    message = str(exc).strip()
    return message or exc.__class__.__name__


class GitProposalMutationAdapter(Protocol):
    """Proposal-only mutation capability injected by a trusted transport boundary."""

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
    patch_program_job_id: str
    repository: str
    proposed_branch: str
    base_commit_sha: str
    base_ref: str
    status: str
    completed_actions: tuple[str, ...]
    operation_evidence: tuple[GitProposalOperationEvidence, ...]
    failure_code: str | None

    def payload(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "plan_digest": self.plan_digest,
            "patch_program_job_id": self.patch_program_job_id,
            "repository": self.repository,
            "proposed_branch": self.proposed_branch,
            "base_commit_sha": self.base_commit_sha,
            "base_ref": self.base_ref,
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
    """Durable persistence capability injected separately from remote mutation."""

    def record(
        self,
        receipt: GitProposalMutationReceipt,
        *,
        event_index: int,
    ) -> GitProposalMutationReceipt: ...

    def latest(self, *, plan_digest: str) -> GitProposalMutationReceipt | None: ...

    def next_event_index(self, *, plan_digest: str) -> int: ...


class GitProposalMutationError(RuntimeError):
    """Failure with exact evidence for side effects verified before the failure."""

    def __init__(self, code: str, receipt: GitProposalMutationReceipt) -> None:
        super().__init__(code)
        self.code = code
        self.receipt = receipt


class GitProposalMutationExecutor:
    """Execute only an exact freshly reverified BUILD-BRAIN-114R v2 plan."""

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
        if plan.patch_program_job_id != request.patch_program_job_id:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_PATCH_JOB_MISMATCH")
        if plan.base_ref != request.base_ref:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_BASE_REF_MISMATCH")
        if plan.repository not in self._repository_allowlist:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_REPOSITORY_NOT_ALLOWED")
        if not plan.proposed_branch.startswith(ALLOWED_BRANCH_PREFIX):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_BRANCH_NOT_ALLOWED")
        if not _is_git_sha(plan.base_commit_sha):
            raise ValueError("GIT_PROPOSAL_EXECUTOR_BASE_COMMIT_INVALID")

        actions = tuple(operation.action for operation in plan.operations)
        if any(action not in ALLOWED_ACTIONS for action in actions):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_ACTION_NOT_ALLOWED")
        _require_dependency_closed_prefix(actions)

        evidence: list[GitProposalOperationEvidence] = []
        completed: list[str] = []
        expected_commit_sha: str | None = None
        event_index = 1

        if self._journal is not None:
            persisted = self._journal.latest(plan_digest=plan.plan_digest)
            event_index = self._journal.next_event_index(plan_digest=plan.plan_digest)
            if persisted is not None:
                self._verify_resume_receipt(plan=plan, receipt=persisted)
                if persisted.status in FINAL_STATUSES:
                    return persisted
                evidence.extend(persisted.operation_evidence)
                completed.extend(persisted.completed_actions)
                expected_commit_sha = self._expected_commit_sha(evidence)

        for operation in plan.operations[len(completed) :]:
            try:
                authorization_gate.verify_grant(request, grant_mapping)
                raw = self._adapter.apply_proposal_operation(
                    plan_digest=plan.plan_digest,
                    operation=operation,
                )
                item = self._verify_operation_evidence(
                    plan=plan,
                    operation=operation,
                    raw=raw,
                    expected_commit_sha=expected_commit_sha,
                )
            except Exception as exc:
                code = _failure_code(exc)
                receipt = self._receipt(
                    plan=plan,
                    status="partial_failure" if completed else "failed",
                    completed=completed,
                    evidence=evidence,
                    failure_code=code,
                )
                self._record(receipt, event_index=event_index)
                raise GitProposalMutationError(code, receipt) from exc

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
            self._record(progress, event_index=event_index)
            event_index += 1

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
        self._record(receipt, event_index=event_index)
        return receipt

    def _record(
        self,
        receipt: GitProposalMutationReceipt,
        *,
        event_index: int,
    ) -> None:
        if self._journal is None:
            return
        persisted = self._journal.record(receipt, event_index=event_index)
        if persisted.snapshot() != receipt.snapshot():
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_JOURNAL_MISMATCH")

    @staticmethod
    def _verify_resume_receipt(
        *,
        plan: GitProposalExecutionPlan,
        receipt: GitProposalMutationReceipt,
    ) -> None:
        if receipt.plan_digest != plan.plan_digest:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_RESUME_PLAN_MISMATCH")
        if (
            receipt.patch_program_job_id != plan.patch_program_job_id
            or receipt.repository != plan.repository
            or receipt.proposed_branch != plan.proposed_branch
            or receipt.base_commit_sha != plan.base_commit_sha
            or receipt.base_ref != plan.base_ref
        ):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_RESUME_IDENTITY_MISMATCH")
        expected_actions = tuple(
            operation.action
            for operation in plan.operations[: len(receipt.completed_actions)]
        )
        if receipt.completed_actions != expected_actions:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_RESUME_ACTION_PREFIX_MISMATCH")
        if len(receipt.operation_evidence) != len(receipt.completed_actions):
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_RESUME_EVIDENCE_MISMATCH")
        if receipt.status in FINAL_STATUSES:
            plan_actions = tuple(operation.action for operation in plan.operations)
            if receipt.completed_actions != plan_actions:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_TERMINAL_INCOMPLETE")
            ends_with_final_action = (
                bool(plan_actions) and plan_actions[-1] == FINAL_ACTION
            )
            if receipt.status == "completed" and not ends_with_final_action:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_TERMINAL_STATUS_MISMATCH")
            if receipt.status == "completed_subset" and ends_with_final_action:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_TERMINAL_STATUS_MISMATCH")

    @staticmethod
    def _expected_commit_sha(
        evidence: Sequence[GitProposalOperationEvidence],
    ) -> str | None:
        for item in evidence:
            if item.action == "create_commit":
                commit = str(item.payload.get("commit_sha") or "").strip().lower()
                if not _is_git_sha(commit):
                    raise PermissionError("GIT_PROPOSAL_EXECUTOR_RESUME_COMMIT_INVALID")
                return commit
        return None

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
            patch_program_job_id=plan.patch_program_job_id,
            repository=plan.repository,
            proposed_branch=plan.proposed_branch,
            base_commit_sha=plan.base_commit_sha,
            base_ref=plan.base_ref,
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
            patch_job = str(payload.get("patch_program_job_id") or "").strip()
            expected_changes = [
                {"path": path, "after_sha256": digest}
                for path, digest in plan.change_hashes
            ]
            if parent != plan.base_commit_sha or not _is_git_sha(commit):
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_COMMIT_EVIDENCE_INVALID")
            if patch_job != plan.patch_program_job_id:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PATCH_JOB_MISMATCH")
            if payload.get("change_hashes") != expected_changes:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_COMMIT_POSTIMAGE_MISMATCH")
        elif action == "push_branch":
            commit = str(payload.get("commit_sha") or "").strip().lower()
            if expected_commit_sha is None or commit != expected_commit_sha:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PUSH_COMMIT_MISMATCH")
        elif action == "open_pull_request":
            head = str(payload.get("head_branch") or "").strip()
            base_ref = str(payload.get("base_ref") or "").strip()
            base = str(payload.get("base_commit_sha") or "").strip().lower()
            head_commit = str(payload.get("head_commit_sha") or "").strip().lower()
            pr_number = payload.get("pull_request_number")
            if (
                head != plan.proposed_branch
                or base_ref != plan.base_ref
                or base != plan.base_commit_sha
            ):
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PR_TARGET_MISMATCH")
            if expected_commit_sha is None or head_commit != expected_commit_sha:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PR_COMMIT_MISMATCH")
            if type(pr_number) is not int or pr_number <= 0:
                raise PermissionError("GIT_PROPOSAL_EXECUTOR_PR_NUMBER_INVALID")
        else:
            raise PermissionError("GIT_PROPOSAL_EXECUTOR_ACTION_NOT_ALLOWED")

        return GitProposalOperationEvidence(
            action=action,
            status=status,
            evidence_digest=canonical_sha256(payload),
            payload=payload,
        )
