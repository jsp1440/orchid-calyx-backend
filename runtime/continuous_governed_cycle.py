"""Continuous owner-gated engineering cycle for Calyx.

This coordinator joins the scheduler, activation bridge, and audited dispatcher.
It remains draft-only and cannot merge, deploy, publish, delete production data,
communicate externally, or change permissions or governance.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from runtime.draft_engineering_executor import EngineeringTask
from runtime.github_connector_dispatcher import (
    AuditedGitHubDispatcher,
    DispatchReceipt,
    GitHubDispatchCommand,
)
from runtime.live_activation_bridge import LiveActivationBridge
from runtime.reactive_scheduler import ReactiveScheduler


@dataclass(frozen=True)
class GovernedCycleResult:
    executed: bool
    reason: str
    receipts: tuple[DispatchReceipt, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "reason": self.reason,
            "receipts": [asdict(item) for item in self.receipts],
        }


class ContinuousGovernedCycle:
    """Run one bounded autonomous draft-engineering cycle when due."""

    def __init__(
        self,
        scheduler: ReactiveScheduler,
        bridge: LiveActivationBridge,
        dispatcher: AuditedGitHubDispatcher,
    ) -> None:
        self._scheduler = scheduler
        self._bridge = bridge
        self._dispatcher = dispatcher

    def run_if_due(
        self,
        *,
        now: datetime,
        select_task: Callable[[], EngineeringTask | None],
        changed_paths: Callable[[EngineeringTask], tuple[str, ...]],
        validation_results: Callable[[EngineeringTask], dict[str, bool]],
        connector_executor: Callable[[GitHubDispatchCommand], dict[str, Any]],
    ) -> GovernedCycleResult:
        def execute_cycle(limit: int) -> GovernedCycleResult:
            task = select_task()
            if task is None:
                return GovernedCycleResult(False, "no-approved-task")

            paths = changed_paths(task)
            validations = validation_results(task)
            prepared = self._bridge.prepare_draft_command(task, paths, validations)
            branch_command = GitHubDispatchCommand(
                repository=task.repository,
                operation="create_branch",
                payload={"branch_name": prepared.branch_name, "base_ref": "main"},
            )
            pull_request_command = GitHubDispatchCommand(
                repository=task.repository,
                operation="create_draft_pull_request",
                payload={
                    "head": prepared.branch_name,
                    "base": "main",
                    "draft": True,
                    "title": prepared.title,
                    "body": prepared.body,
                },
            )
            receipts = (
                self._dispatcher.dispatch(branch_command, connector_executor),
                self._dispatcher.dispatch(pull_request_command, connector_executor),
            )
            return GovernedCycleResult(True, f"executed-with-limit-{limit}", receipts)

        scheduled = self._scheduler.run_if_due(execute_cycle, now)
        if isinstance(scheduled, GovernedCycleResult):
            return scheduled
        if scheduled.get("executed") is False:
            return GovernedCycleResult(False, scheduled.get("reason", "not-due"))
        result = scheduled.get("result")
        if isinstance(result, GovernedCycleResult):
            return result
        raise RuntimeError("scheduler returned an unsupported cycle result")

    def status(self) -> dict[str, Any]:
        return {
            "mode": "governed-draft-engineering",
            "automatic_merge": False,
            "automatic_deploy": False,
            "scientific_publication": False,
            "production_deletion": False,
            "external_communication": False,
            "permissions_change": False,
            "governance_change": False,
        }
