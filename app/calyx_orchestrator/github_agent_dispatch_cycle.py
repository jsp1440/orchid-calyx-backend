from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

from sqlalchemy.orm import Session

from .assignment_factory import governed_assignment_from_claimed_job
from .engineering_core import TerminalOutcome
from .executor import GovernedAssignment
from .github_agent_dispatch_store import DurableGitHubAgentDispatchStore
from .github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
    LifecycleAction,
    PullRequestObservation,
    reconcile_agent_lifecycle,
    record_repair_request,
)
from .github_coding_executor import (
    GITHUB_CODING_ROLE,
    BudgetClass,
    GitHubCodingAgentExecutor,
)
from .program_worker import PersistentProgramWorker

EXECUTE_CONFIRMATION = "DISPATCH_GITHUB_CODING_AGENT"
_BUDGET_RANK = {
    BudgetClass.TINY: 0,
    BudgetClass.SMALL: 1,
    BudgetClass.NORMAL: 2,
    BudgetClass.DEEP: 3,
    BudgetClass.EXCEPTIONAL: 4,
}


@dataclass(frozen=True, slots=True)
class GitHubCodingRuntimePolicy:
    enabled: bool = False
    owner_allowlist: frozenset[str] = frozenset()
    repository_allowlist: frozenset[str] = frozenset()
    max_budget_class: BudgetClass = BudgetClass.NORMAL

    def validate_owner(self, owner: str) -> None:
        if not self.enabled:
            raise PermissionError("GITHUB_CODING_RUNTIME_DISABLED")
        if owner not in self.owner_allowlist:
            raise PermissionError("GITHUB_CODING_OWNER_NOT_ALLOWED")

    def validate_assignment(self, assignment: GovernedAssignment) -> BudgetClass:
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("GITHUB_CODING_JOB_INPUT_REQUIRED")
        repository = str(job.get("repository") or "").strip()
        if repository not in self.repository_allowlist:
            raise PermissionError("GITHUB_CODING_REPOSITORY_NOT_ALLOWED")
        if not bool(job.get("mutating_intent")):
            raise PermissionError("GITHUB_CODING_MUTATING_INTENT_REQUIRED")
        try:
            budget = BudgetClass(str(job.get("budget_class") or "NORMAL").upper())
        except ValueError as exc:
            raise ValueError("GITHUB_CODING_BUDGET_CLASS_INVALID") from exc
        if _BUDGET_RANK[budget] > _BUDGET_RANK[self.max_budget_class]:
            raise PermissionError("GITHUB_CODING_BUDGET_CLASS_EXCEEDS_POLICY")
        return budget

    @staticmethod
    def require_execute_confirmation(*, execute: bool, confirmation: str | None) -> None:
        if execute and confirmation != EXECUTE_CONFIRMATION:
            raise PermissionError("GITHUB_CODING_EXECUTE_CONFIRMATION_REQUIRED")


@dataclass(frozen=True, slots=True)
class ClaimedGitHubCodingJob:
    program_job_id: str
    worker_id: str
    lease_token: str
    assignment: GovernedAssignment


class CodingJobLeaseGateway(Protocol):
    def claim(self, *, owner: str) -> ClaimedGitHubCodingJob | None: ...

    def release_preflight(self, claim: ClaimedGitHubCodingJob) -> None: ...

    def complete(
        self,
        claim: ClaimedGitHubCodingJob,
        *,
        outcome: TerminalOutcome,
        evidence: dict[str, object],
        blocker: str | None = None,
        human_action: str | None = None,
    ) -> None: ...


class DispatchStoreGateway(Protocol):
    def get(self, *, program_job_id: str) -> GitHubAgentDispatchRecord | None: ...

    def record(self, dispatch: GitHubAgentDispatchRecord) -> GitHubAgentDispatchRecord: ...


class AgentObservationGateway(Protocol):
    def observe(self, dispatch: GitHubAgentDispatchRecord) -> PullRequestObservation: ...


class RepairRequestGateway(Protocol):
    def request_repair(
        self,
        dispatch: GitHubAgentDispatchRecord,
        *,
        failure_class: str,
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class DispatchCycleResult:
    state: str
    program_job_id: str | None = None
    mission_id: str | None = None
    repository: str | None = None
    issue_number: int | None = None
    pull_request_number: int | None = None
    action: str | None = None
    reason: str | None = None
    side_effects: tuple[str, ...] = ()


class SqlAlchemyCodingJobLeaseGateway:
    """Adapter around the existing durable Calyx program-worker lease contract."""

    def __init__(
        self,
        db: Session,
        *,
        worker_id: str = "github-coding-agent-dispatch",
        lease_seconds: int = 300,
    ) -> None:
        self.db = db
        self.worker = PersistentProgramWorker(db)
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    def claim(self, *, owner: str) -> ClaimedGitHubCodingJob | None:
        job = self.worker.claim(
            worker_id=self.worker_id,
            lease_seconds=self.lease_seconds,
            owner=owner,
            allowed_role_keys=frozenset({GITHUB_CODING_ROLE}),
        )
        if job is None:
            return None
        if not job.lease_token:
            raise PermissionError("GITHUB_CODING_LIVE_LEASE_TOKEN_REQUIRED")
        assignment = governed_assignment_from_claimed_job(
            self.db,
            owner=owner,
            job=job,
            timeout_seconds=min(self.lease_seconds, 300),
        )
        return ClaimedGitHubCodingJob(
            program_job_id=job.program_job_id,
            worker_id=self.worker_id,
            lease_token=job.lease_token,
            assignment=assignment,
        )

    def release_preflight(self, claim: ClaimedGitHubCodingJob) -> None:
        self.worker.release_preflight(
            program_job_id=claim.program_job_id,
            worker_id=claim.worker_id,
            lease_token=claim.lease_token,
        )

    def complete(
        self,
        claim: ClaimedGitHubCodingJob,
        *,
        outcome: TerminalOutcome,
        evidence: dict[str, object],
        blocker: str | None = None,
        human_action: str | None = None,
    ) -> None:
        self.worker.complete(
            program_job_id=claim.program_job_id,
            worker_id=claim.worker_id,
            lease_token=claim.lease_token,
            outcome=outcome.value,
            evidence=evidence,
            blocker=blocker,
            human_action=human_action,
        )


class GitHubCodingAgentDispatchCycle:
    """One bounded asynchronous dispatch/reconciliation iteration.

    Default policy is disabled. Preflight can claim/release a candidate without
    provider side effects. Execute mode requires the exact confirmation token.
    Coding-agent assignment is never treated as mission completion; the durable
    Calyx job completes only after the lifecycle observer proves owner-governed
    merge or when an explicit terminal blocker is recorded.
    """

    def __init__(
        self,
        *,
        policy: GitHubCodingRuntimePolicy,
        leases: CodingJobLeaseGateway,
        store: DispatchStoreGateway,
        executor: GitHubCodingAgentExecutor,
        observer: AgentObservationGateway,
        repairer: RepairRequestGateway,
    ) -> None:
        self.policy = policy
        self.leases = leases
        self.store = store
        self.executor = executor
        self.observer = observer
        self.repairer = repairer

    def run_once(
        self,
        *,
        owner: str,
        execute: bool = False,
        confirmation: str | None = None,
    ) -> DispatchCycleResult:
        self.policy.validate_owner(owner)
        self.policy.require_execute_confirmation(execute=execute, confirmation=confirmation)
        claim = self.leases.claim(owner=owner)
        if claim is None:
            return DispatchCycleResult(state="idle")

        try:
            budget = self.policy.validate_assignment(claim.assignment)
        except Exception:
            self.leases.release_preflight(claim)
            raise

        existing = self.store.get(program_job_id=claim.program_job_id)
        if existing is None:
            if not execute:
                self.leases.release_preflight(claim)
                job = self._job(claim.assignment)
                return DispatchCycleResult(
                    state="preflight_ready",
                    program_job_id=claim.program_job_id,
                    mission_id=str(job.get("mission_id") or claim.assignment.job_key),
                    repository=str(job.get("repository") or ""),
                    action="would_dispatch",
                    reason=f"budget={budget.value}",
                    side_effects=(),
                )
            authorized = self._authorize_assignment(claim.assignment)
            receipt = self.executor.execute(authorized)
            status = str(receipt.output.get("status") or "")
            if status == "already_done":
                evidence = {
                    "status": status,
                    "receipt": dict(receipt.output),
                    "evidence_uris": list(receipt.evidence_uris),
                }
                self.leases.complete(
                    claim,
                    outcome=TerminalOutcome.NO_OP,
                    evidence=evidence,
                )
                return DispatchCycleResult(
                    state="already_done",
                    program_job_id=claim.program_job_id,
                    mission_id=str(receipt.output.get("mission_id") or claim.assignment.job_key),
                    repository=str(receipt.output.get("repository") or ""),
                    action="completed_no_op",
                    side_effects=(),
                )
            if status != "agent_assigned":
                self.leases.release_preflight(claim)
                return DispatchCycleResult(
                    state="dispatch_not_accepted",
                    program_job_id=claim.program_job_id,
                    reason=status or receipt.blocker_code or "UNKNOWN_DISPATCH_STATE",
                )
            issue_number = int(receipt.output.get("issue_number") or 0)
            if issue_number <= 0:
                self.leases.release_preflight(claim)
                raise ValueError("GITHUB_CODING_DISPATCH_ISSUE_REQUIRED")
            dispatch = GitHubAgentDispatchRecord(
                program_job_id=claim.program_job_id,
                mission_id=str(receipt.output.get("mission_id") or claim.assignment.job_key),
                repository=str(receipt.output.get("repository") or ""),
                base_sha=str(receipt.output.get("base_sha") or ""),
                provider=str(receipt.output.get("provider") or ""),
                issue_number=issue_number,
                state=AgentLifecycleState.AGENT_ASSIGNED,
            )
            persisted = self.store.record(dispatch)
            self.leases.release_preflight(claim)
            return DispatchCycleResult(
                state=persisted.state.value,
                program_job_id=claim.program_job_id,
                mission_id=persisted.mission_id,
                repository=persisted.repository,
                issue_number=persisted.issue_number,
                action="agent_assigned",
                side_effects=("github_issue_agent_assignment",),
            )

        observation = self.observer.observe(existing)
        decision = reconcile_agent_lifecycle(existing, observation)
        persisted = self.store.record(decision.record)

        if decision.action in {LifecycleAction.AWAIT, LifecycleAction.OWNER_REVIEW}:
            self.leases.release_preflight(claim)
            return self._decision_result(claim, persisted, decision.action, decision.reason)

        if decision.action == LifecycleAction.REQUEST_REPAIR:
            failure_class = persisted.last_failure_class or observation.failure_class or "required_ci_failure"
            if not execute:
                self.leases.release_preflight(claim)
                return self._decision_result(
                    claim,
                    persisted,
                    decision.action,
                    "REPAIR_REQUIRED_PREFLIGHT_ONLY",
                )
            evidence_uri = self.repairer.request_repair(
                persisted,
                failure_class=failure_class,
            )
            repaired = record_repair_request(persisted, failure_class=failure_class)
            repaired = self.store.record(repaired)
            self.leases.release_preflight(claim)
            return DispatchCycleResult(
                state=repaired.state.value,
                program_job_id=claim.program_job_id,
                mission_id=repaired.mission_id,
                repository=repaired.repository,
                issue_number=repaired.issue_number,
                pull_request_number=repaired.pull_request_number,
                action="repair_requested",
                reason=failure_class,
                side_effects=(evidence_uri,),
            )

        if decision.action == LifecycleAction.MARK_DELIVERED:
            evidence = {
                "status": "merged",
                "mission_id": persisted.mission_id,
                "repository": persisted.repository,
                "base_sha": persisted.base_sha,
                "issue_number": persisted.issue_number,
                "pull_request_number": persisted.pull_request_number,
                "pull_request_url": persisted.pull_request_url,
                "head_sha": persisted.head_sha,
                "provider": persisted.provider,
                "owner_governed_merge_observed": True,
            }
            self.leases.complete(
                claim,
                outcome=TerminalOutcome.DELIVERED,
                evidence=evidence,
            )
            return self._decision_result(claim, persisted, decision.action, decision.reason)

        if decision.action == LifecycleAction.ESCALATE:
            evidence = {
                "status": "blocked",
                "mission_id": persisted.mission_id,
                "repository": persisted.repository,
                "issue_number": persisted.issue_number,
                "pull_request_number": persisted.pull_request_number,
                "failure_class": persisted.last_failure_class,
                "repair_attempts": persisted.repair_attempts,
            }
            self.leases.complete(
                claim,
                outcome=TerminalOutcome.BLOCKED,
                evidence=evidence,
                blocker=decision.reason,
                human_action="Review the coding-agent PR and choose a governed repair or supersession.",
            )
            return self._decision_result(claim, persisted, decision.action, decision.reason)

        self.leases.release_preflight(claim)
        raise RuntimeError("GITHUB_CODING_LIFECYCLE_ACTION_UNSUPPORTED")

    @staticmethod
    def _authorize_assignment(assignment: GovernedAssignment) -> GovernedAssignment:
        inputs = dict(assignment.inputs)
        governance = dict(inputs.get("governance") or {})
        governance.update(
            {
                "external_execution_authorized": True,
                "repository_code_execution_authorized": True,
                "automatic_merge_authorized": False,
                "deployment_authorized": False,
                "publication_authorized": False,
                "production_graph_mutation_authorized": False,
            }
        )
        inputs["governance"] = governance
        return replace(
            assignment,
            inputs=inputs,
            requested_capabilities=(
                *assignment.requested_capabilities,
                "github_agent_dispatch",
            ),
            input_checksum=None,
        )

    @staticmethod
    def _job(assignment: GovernedAssignment) -> dict[str, object]:
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("GITHUB_CODING_JOB_INPUT_REQUIRED")
        return job

    @staticmethod
    def _decision_result(
        claim: ClaimedGitHubCodingJob,
        dispatch: GitHubAgentDispatchRecord,
        action: LifecycleAction,
        reason: str,
    ) -> DispatchCycleResult:
        return DispatchCycleResult(
            state=dispatch.state.value,
            program_job_id=claim.program_job_id,
            mission_id=dispatch.mission_id,
            repository=dispatch.repository,
            issue_number=dispatch.issue_number,
            pull_request_number=dispatch.pull_request_number,
            action=action.value,
            reason=reason,
        )


def build_sqlalchemy_dispatch_store(db: Session) -> DurableGitHubAgentDispatchStore:
    return DurableGitHubAgentDispatchStore(db)
