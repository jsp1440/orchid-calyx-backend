from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from .github_coding_executor import MAX_SAME_FAILURE_RETRIES


class AgentLifecycleState(StrEnum):
    AGENT_ASSIGNED = "agent_assigned"
    AWAITING_PR = "awaiting_pr"
    CI_PENDING = "ci_pending"
    REPAIR_REQUIRED = "repair_required"
    READY_FOR_OWNER_REVIEW = "ready_for_owner_review"
    MERGED = "merged"
    BLOCKED = "blocked"


class LifecycleAction(StrEnum):
    AWAIT = "await"
    REQUEST_REPAIR = "request_repair"
    OWNER_REVIEW = "owner_review"
    MARK_DELIVERED = "mark_delivered"
    ESCALATE = "escalate"


@dataclass(frozen=True, slots=True)
class GitHubAgentDispatchRecord:
    """branch is the authoritative branch identity reserved for this mission
    at admission time (CalyxProgramJob.branch / EngineeringAdmissionPolicy's
    per-branch mutation lock) - it is set once, at dispatch creation, and is
    immutable thereafter (see DurableGitHubAgentDispatchStore._validate_identity).
    It is NOT necessarily the same string as whatever branch the coding-agent
    provider actually creates once assigned; head_sha is the durable pointer
    to the real, observed commit once a PR exists. branch answers "what was
    this mission's exclusivity lock," head_sha answers "what did the agent
    actually produce" - they are deliberately two different questions.
    """

    program_job_id: str
    mission_id: str
    repository: str
    base_sha: str
    provider: str
    issue_number: int
    state: AgentLifecycleState = AgentLifecycleState.AGENT_ASSIGNED
    branch: str | None = None
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    head_sha: str | None = None
    repair_attempts: int = 0
    last_failure_class: str | None = None

    def verify(self) -> None:
        if not self.program_job_id or not self.mission_id or not self.repository:
            raise ValueError("GITHUB_AGENT_DISPATCH_IDENTITY_REQUIRED")
        if self.branch is not None and not self.branch.strip():
            raise ValueError("GITHUB_AGENT_DISPATCH_BRANCH_INVALID")
        if len(self.base_sha) != 40:
            raise ValueError("GITHUB_AGENT_DISPATCH_BASE_SHA_INVALID")
        if self.issue_number <= 0:
            raise ValueError("GITHUB_AGENT_DISPATCH_ISSUE_INVALID")
        if self.pull_request_number is not None and self.pull_request_number <= 0:
            raise ValueError("GITHUB_AGENT_DISPATCH_PR_INVALID")
        if self.repair_attempts < 0:
            raise ValueError("GITHUB_AGENT_DISPATCH_REPAIR_ATTEMPTS_INVALID")


@dataclass(frozen=True, slots=True)
class PullRequestObservation:
    repository: str
    issue_number: int
    pull_request_number: int | None = None
    pull_request_url: str | None = None
    draft: bool | None = None
    merged: bool = False
    head_sha: str | None = None
    required_checks_known: bool = False
    required_checks_pending: tuple[str, ...] = ()
    required_checks_failed: tuple[str, ...] = ()
    required_checks_succeeded: tuple[str, ...] = ()
    infrastructure_failure: bool = False
    failure_class: str | None = None


@dataclass(frozen=True, slots=True)
class LifecycleDecision:
    record: GitHubAgentDispatchRecord
    action: LifecycleAction
    reason: str
    dependency_release_allowed: bool = False


def reconcile_agent_lifecycle(
    record: GitHubAgentDispatchRecord,
    observation: PullRequestObservation,
) -> LifecycleDecision:
    """Reconcile asynchronous coding-agent work without crossing owner merge authority.

    The durable Calyx mission remains non-terminal until the exact PR is observed
    merged. Green CI only reaches owner-review readiness; it never releases dependent
    missions. Infrastructure failures never consume the coding-repair budget.
    """

    record.verify()
    if observation.repository != record.repository:
        raise PermissionError("GITHUB_AGENT_OBSERVATION_REPOSITORY_MISMATCH")
    if observation.issue_number != record.issue_number:
        raise PermissionError("GITHUB_AGENT_OBSERVATION_ISSUE_MISMATCH")
    if (
        record.pull_request_number is not None
        and observation.pull_request_number is not None
        and observation.pull_request_number != record.pull_request_number
    ):
        raise PermissionError("GITHUB_AGENT_OBSERVATION_PR_MISMATCH")
    if record.head_sha is not None and observation.merged and observation.head_sha is None:
        raise ValueError("GITHUB_AGENT_MERGED_HEAD_EVIDENCE_REQUIRED")

    updated = record
    if observation.pull_request_number is None:
        updated = replace(record, state=AgentLifecycleState.AWAITING_PR)
        return LifecycleDecision(updated, LifecycleAction.AWAIT, "COPILOT_PR_NOT_OPEN_YET")

    if updated.pull_request_number is None:
        updated = replace(
            updated,
            pull_request_number=observation.pull_request_number,
            pull_request_url=observation.pull_request_url,
            head_sha=observation.head_sha,
        )
    elif observation.head_sha:
        updated = replace(updated, head_sha=observation.head_sha)

    if observation.merged:
        if not observation.head_sha:
            raise ValueError("GITHUB_AGENT_MERGED_HEAD_EVIDENCE_REQUIRED")
        merged = replace(updated, state=AgentLifecycleState.MERGED, head_sha=observation.head_sha)
        return LifecycleDecision(
            merged,
            LifecycleAction.MARK_DELIVERED,
            "OWNER_GOVERNED_MERGE_OBSERVED",
            dependency_release_allowed=True,
        )

    if observation.infrastructure_failure:
        waiting = replace(updated, state=AgentLifecycleState.CI_PENDING)
        return LifecycleDecision(
            waiting,
            LifecycleAction.AWAIT,
            "CI_INFRASTRUCTURE_FAILURE_DOES_NOT_CONSUME_REPAIR_BUDGET",
        )

    if not observation.required_checks_known or observation.required_checks_pending:
        waiting = replace(updated, state=AgentLifecycleState.CI_PENDING)
        return LifecycleDecision(waiting, LifecycleAction.AWAIT, "REQUIRED_CI_NOT_COMPLETE")

    if observation.required_checks_failed:
        failure_class = observation.failure_class or "required_ci_failure"
        if updated.repair_attempts >= MAX_SAME_FAILURE_RETRIES:
            blocked = replace(
                updated,
                state=AgentLifecycleState.BLOCKED,
                last_failure_class=failure_class,
            )
            return LifecycleDecision(
                blocked,
                LifecycleAction.ESCALATE,
                "SAME_FAILURE_REPAIR_BUDGET_EXHAUSTED",
            )
        repair = replace(
            updated,
            state=AgentLifecycleState.REPAIR_REQUIRED,
            last_failure_class=failure_class,
        )
        return LifecycleDecision(
            repair,
            LifecycleAction.REQUEST_REPAIR,
            "REQUIRED_CI_FAILED",
        )

    if observation.draft is not True:
        blocked = replace(updated, state=AgentLifecycleState.BLOCKED)
        return LifecycleDecision(
            blocked,
            LifecycleAction.ESCALATE,
            "CODING_AGENT_PR_MUST_REMAIN_DRAFT",
        )

    ready = replace(updated, state=AgentLifecycleState.READY_FOR_OWNER_REVIEW)
    return LifecycleDecision(
        ready,
        LifecycleAction.OWNER_REVIEW,
        "EXACT_REQUIRED_CI_GREEN_OWNER_MERGE_REQUIRED",
        dependency_release_allowed=False,
    )


def record_repair_request(
    record: GitHubAgentDispatchRecord,
    *,
    failure_class: str,
) -> GitHubAgentDispatchRecord:
    """Increment repair budget only after a repair request was durably accepted."""

    record.verify()
    if record.state != AgentLifecycleState.REPAIR_REQUIRED:
        raise PermissionError("GITHUB_AGENT_REPAIR_NOT_REQUIRED")
    if record.repair_attempts >= MAX_SAME_FAILURE_RETRIES:
        raise PermissionError("GITHUB_AGENT_REPAIR_BUDGET_EXHAUSTED")
    return replace(
        record,
        state=AgentLifecycleState.CI_PENDING,
        repair_attempts=record.repair_attempts + 1,
        last_failure_class=failure_class,
    )
