from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .github import GitHubEngineeringClient
from .provider import StructuredPatchProvider
from .repair_loop import BoundedRepairLoop, RepairResult


MAX_REPAIR_ATTEMPTS = 3


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
            "autonomous_merge": self.autonomous_merge,
            "deployment": self.deployment,
        }


class GovernedAutonomousCompletionLoop:
    """Advance one draft PR through a bounded CI -> repair -> CI cycle.

    One invocation performs at most one mutating repair. CI is asynchronous, so a
    caller or scheduled worker invokes this method again after GitHub reports the
    new head's checks. Merge and deployment are intentionally outside this class.
    """

    def __init__(
        self,
        client: GitHubEngineeringClient,
        *,
        repair_factory=None,
    ) -> None:
        self.client = client
        self.repair_factory = repair_factory or (
            lambda client: BoundedRepairLoop(
                client,
                StructuredPatchProvider(),
            )
        )

    @staticmethod
    def _workflow_state(runs: list[dict]) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        failed: list[str] = []
        pending: list[str] = []
        successful: list[str] = []
        for run in runs:
            name = str(run.get("name") or f"workflow-{run.get('id', 'unknown')}")
            status = str(run.get("status") or "")
            conclusion = str(run.get("conclusion") or "")
            if status != "completed":
                pending.append(name)
            elif conclusion == "success":
                successful.append(name)
            else:
                failed.append(name)
        return tuple(sorted(set(failed))), tuple(sorted(set(pending))), tuple(sorted(set(successful)))

    def advance(
        self,
        *,
        pull_request_number: int,
        repair_paths: list[str],
        objective: str,
        attempt: int,
        repairs_authorized: bool,
    ) -> CompletionReceipt:
        if attempt < 1:
            raise ValueError("COMPLETION_ATTEMPT_INVALID")
        pull_request = self.client.pull_request(pull_request_number)
        head = pull_request.get("head") or {}
        branch = str(head.get("ref") or "")
        head_sha = str(head.get("sha") or "")

        if pull_request.get("state") != "open" or not pull_request.get("draft", False) or not branch or not head_sha:
            return CompletionReceipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.HALTED_UNSAFE_PR_STATE,
                attempt=attempt,
                attempt_limit=MAX_REPAIR_ATTEMPTS,
                failed_workflows=(),
                pending_workflows=(),
                successful_workflows=(),
                next_action="human_review_pr_state",
            )

        runs = self.client.workflow_runs_for_head(head_sha)
        failed, pending, successful = self._workflow_state(runs)

        if pending or not runs:
            return CompletionReceipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.WAITING_FOR_CI,
                attempt=attempt,
                attempt_limit=MAX_REPAIR_ATTEMPTS,
                failed_workflows=failed,
                pending_workflows=pending,
                successful_workflows=successful,
                next_action="recheck_after_ci",
            )

        if not failed:
            return CompletionReceipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.READY_FOR_MERGE,
                attempt=attempt,
                attempt_limit=MAX_REPAIR_ATTEMPTS,
                failed_workflows=(),
                pending_workflows=(),
                successful_workflows=successful,
                next_action="evaluate_merge_policy",
            )

        if attempt > MAX_REPAIR_ATTEMPTS:
            return CompletionReceipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.HALTED_REPAIR_LIMIT,
                attempt=attempt,
                attempt_limit=MAX_REPAIR_ATTEMPTS,
                failed_workflows=failed,
                pending_workflows=(),
                successful_workflows=successful,
                next_action="human_review_repair_limit",
            )

        if not repairs_authorized:
            return CompletionReceipt(
                pull_request_number=pull_request_number,
                head_sha=head_sha,
                branch=branch,
                state=CompletionState.FAILED_REPAIRABLE,
                attempt=attempt,
                attempt_limit=MAX_REPAIR_ATTEMPTS,
                failed_workflows=failed,
                pending_workflows=(),
                successful_workflows=successful,
                next_action="authorize_bounded_repair",
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
            return CompletionReceipt(
                pull_request_number=pull_request_number,
                head_sha=str(refreshed_head.get("sha") or head_sha),
                branch=str(refreshed_head.get("ref") or branch),
                state=CompletionState.REPAIR_COMMITTED,
                attempt=attempt,
                attempt_limit=MAX_REPAIR_ATTEMPTS,
                failed_workflows=failed,
                pending_workflows=(),
                successful_workflows=successful,
                commits=repair.commits,
                next_action="recheck_after_ci",
            )

        return CompletionReceipt(
            pull_request_number=pull_request_number,
            head_sha=head_sha,
            branch=branch,
            state=CompletionState.HALTED_NO_REPAIR,
            attempt=attempt,
            attempt_limit=MAX_REPAIR_ATTEMPTS,
            failed_workflows=failed,
            pending_workflows=(),
            successful_workflows=successful,
            commits=repair.commits,
            next_action="human_review_no_repair_generated",
        )
