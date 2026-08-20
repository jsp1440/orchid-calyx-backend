from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy

from .github import GitHubEngineeringClient
from .provider import StructuredPatchProvider
from .repair_loop import BoundedRepairLoop, RepairResult

MAX_REPAIR_ATTEMPTS = 3
_INFRASTRUCTURE_CONCLUSIONS = frozenset(
    {"cancelled", "timed_out", "action_required", "stale"}
)


class CompletionState(StrEnum):
    WAITING_FOR_CI = "waiting_for_ci"
    FAILED_REPAIRABLE = "failed_repairable"
    REPAIRING = "repairing"
    REPAIR_COMMITTED = "repair_committed_waiting_for_ci"
    READY_FOR_MERGE = "ready_for_merge"
    HALTED_REPAIR_LIMIT = "halted_repair_limit"
    HALTED_UNSAFE_PR_STATE = "halted_unsafe_pr_state"
    HALTED_NO_REPAIR = "halted_no_repair"


@dataclass(frozen=True)
class CompletionReceipt:
    pull_request_number: int
    head_sha: str
    branch: str
    state: CompletionState
    attempt: int
    attempt_limit: int
    failed_workflows: tuple[str, ...]
    pending_workflows: tuple[str, ...]
    successful_workflows: tuple[str, ...]
    commits: int = 0
    next_action: str = ""
    required_checks_known: bool = False
    infrastructure_failure: bool = False
    autonomous_merge: bool = False
    deployment: bool = False

    def to_dict(self) -> dict:
        return {
            "pull_request_number": self.pull_request_number,
            "head_sha": self.head_sha,
            "branch": self.branch,
            "state": self.state.value,
            "attempt": self.attempt,
            "attempt_limit": self.attempt_limit,
            "attempts_remaining": max(0, self.attempt_limit - self.attempt),
            "failed_workflows": list(self.failed_workflows),
            "pending_workflows": list(self.pending_workflows),
            "successful_workflows": list(self.successful_workflows),
            "commits": self.commits,
            "next_action": self.next_action,
            "required_checks_known": self.required_checks_known,
            "infrastructure_failure": self.infrastructure_failure,
            "autonomous_merge": self.autonomous_merge,
            "deployment": self.deployment,
        }


class GovernedAutonomousCompletionLoop:
    """Advance one draft PR through a bounded CI -> repair -> CI cycle.

    Readiness is established only against an explicit required-check roster. Missing
    checks and infrastructure-only conclusions fail closed and never consume repair
    budget. One invocation performs at most one mutating repair; merge and deployment
    remain outside this class.
    """

    def __init__(
        self,
        client: GitHubEngineeringClient,
        *,
        repair_factory=None,
    ) -> None:
        self.client = client
        self.repair_factory = repair_factory or (
            lambda client: BoundedRepairLoop(client, StructuredPatchProvider())
        )

    @staticmethod
    def _check_conclusions(check_runs: list[dict]) -> tuple[dict[str, str | None], tuple[str, ...]]:
        conclusions: dict[str, str | None] = {}
        infrastructure: set[str] = set()
        for run in check_runs:
            name = str(run.get("name") or "").strip()
            if not name:
                continue
            status = str(run.get("status") or "")
            conclusion = str(run.get("conclusion") or "").strip() or None
            conclusions[name] = conclusion if status == "completed" else None
            if status == "completed" and conclusion in _INFRASTRUCTURE_CONCLUSIONS:
                infrastructure.add(name)
        return conclusions, tuple(sorted(infrastructure))

    def _receipt(
        self,
        *,
        pull_request_number: int,
        head_sha: str,
        branch: str,
        state: CompletionState,
        attempt: int,
        failed: tuple[str, ...] = (),
        pending: tuple[str, ...] = (),
        successful: tuple[str, ...] = (),
        commits: int = 0,
        next_action: str = "",
        required_checks_known: bool = False,
        infrastructure_failure: bool = False,
    ) -> CompletionReceipt:
        return CompletionReceipt(
            pull_request_number=pull_request_number,
            head_sha=head_sha,
            branch=branch,
            state=state,
            attempt=attempt,
            attempt_limit=MAX_REPAIR_ATTEMPTS,
            failed_workflows=failed,
            pending_workflows=pending,
            successful_workflows=successful,
            commits=commits,
            next_action=next_action,
            required_checks_known=required_checks_known,
            infrastructure_failure=infrastructure_failure,
        )

    def advance(
        self,
        *,
        pull_request_number: int,
        repair_paths: list[str],
        objective: str,
        attempt: int,
        repairs_authorized: bool,
        required_checks: list[str],
    ) -> CompletionReceipt:
        if attempt < 1:
            raise ValueError("COMPLETION_ATTEMPT_INVALID")
        normalized_required = frozenset(
            str(name).strip() for name in required_checks if str(name).strip()
        )
        if not normalized_required:
            raise ValueError("ENGINEERING_COMPLETION_REQUIRED_CHECKS_REQUIRED")

        pull_request = self.client.pull_request(pull_request_number)
        head = pull_request.get("head") or {}
        branch = str(head.get("ref") or "")
        head_sha = str(head.get("sha") or "")
        if (
            pull_request.get("state") != "open"
            or not pull_request.get("draft", False)
            or not branch
            or not head_sha
        ):
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.HALTED_UNSAFE_PR_STATE,
                attempt=attempt,
                next_action="human_review_pr_state",
            )

        check_runs = self.client.check_runs_for_head(head_sha)
        conclusions, infrastructure_checks = self._check_conclusions(check_runs)
        assessment = RequiredCiCheckPolicy(required_checks=normalized_required).evaluate(conclusions)
        failed = assessment.required_checks_failed
        pending = assessment.required_checks_pending
        successful = assessment.required_checks_succeeded

        if assessment.infrastructure_failure:
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.WAITING_FOR_CI,
                attempt=attempt,
                pending=tuple(sorted(set(pending) | set(infrastructure_checks))),
                successful=successful,
                next_action="retry_infrastructure_checks",
                required_checks_known=assessment.required_checks_known,
                infrastructure_failure=True,
            )

        if pending or not assessment.required_checks_known:
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.WAITING_FOR_CI,
                attempt=attempt,
                failed=failed,
                pending=pending,
                successful=successful,
                next_action="recheck_after_ci",
                required_checks_known=assessment.required_checks_known,
            )

        if not failed:
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.READY_FOR_MERGE,
                attempt=attempt,
                successful=successful,
                next_action="evaluate_merge_policy",
                required_checks_known=True,
            )

        if attempt > MAX_REPAIR_ATTEMPTS:
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.HALTED_REPAIR_LIMIT,
                attempt=attempt,
                failed=failed,
                successful=successful,
                next_action="human_review_repair_limit",
                required_checks_known=True,
            )

        if not repairs_authorized:
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.FAILED_REPAIRABLE,
                attempt=attempt,
                failed=failed,
                successful=successful,
                next_action="authorize_bounded_repair",
                required_checks_known=True,
            )

        repair: RepairResult = self.repair_factory(self.client).repair_once(
            pull_request_number=pull_request_number,
            paths=repair_paths,
            objective=objective,
            attempt=attempt,
        )
        if repair.status == "repair_committed_waiting_for_ci":
            refreshed = self.client.pull_request(pull_request_number)
            refreshed_head = refreshed.get("head") or {}
            return self._receipt(
                pull_request_number=pull_request_number,
                head_sha=str(refreshed_head.get("sha") or head_sha),
                branch=str(refreshed_head.get("ref") or branch),
                state=CompletionState.REPAIR_COMMITTED,
                attempt=attempt,
                failed=failed,
                successful=successful,
                commits=repair.commits,
                next_action="recheck_after_ci",
                required_checks_known=True,
            )

        return self._receipt(
            pull_request_number=pull_request_number,
            head_sha=head_sha,
            branch=branch,
            state=CompletionState.HALTED_NO_REPAIR,
            attempt=attempt,
            failed=failed,
            successful=successful,
            commits=repair.commits,
            next_action="human_review_no_repair_generated",
            required_checks_known=True,
        )
