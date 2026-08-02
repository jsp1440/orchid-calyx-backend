"""Owner-gated live activation bridge for governed Calyx runtime cycles.

This bridge composes existing self-audit, scheduling, queue, and draft-engineering
contracts. It prepares connector commands but does not execute GitHub writes,
merge, deploy, publish, delete, communicate externally, or change governance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from runtime.draft_engineering_executor import (
    EngineeringTask,
    GovernedDraftEngineeringExecutor,
)
from runtime.reactive_scheduler import ReactiveScheduler


@dataclass(frozen=True)
class ActivationPolicy:
    enabled: bool = False
    owner_approved: bool = False
    repository_allowlist: tuple[str, ...] = ()
    max_draft_prs_per_cycle: int = 1

    def validated(self) -> ActivationPolicy:
        if not 0 <= self.max_draft_prs_per_cycle <= 5:
            raise ValueError("max_draft_prs_per_cycle must be between 0 and 5")
        return self


@dataclass(frozen=True)
class ConnectorCommand:
    operation: str
    repository: str
    branch_name: str
    title: str
    body: str
    draft: bool
    expected_base: str = "main"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiveActivationBridge:
    """Prepare bounded GitHub connector commands while failing closed."""

    def __init__(
        self,
        policy: ActivationPolicy,
        scheduler: ReactiveScheduler,
        executor: GovernedDraftEngineeringExecutor | None = None,
    ) -> None:
        self.policy = policy.validated()
        self.scheduler = scheduler
        self.executor = executor or GovernedDraftEngineeringExecutor()

    def status(self) -> dict[str, Any]:
        authorized = self.policy.enabled and self.policy.owner_approved
        return {
            "enabled": self.policy.enabled,
            "owner_approved": self.policy.owner_approved,
            "authorized": authorized,
            "mode": "governed_draft_only",
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_publication": False,
            "external_communication": False,
        }

    def prepare_draft_command(
        self,
        task: EngineeringTask,
        changed_paths: tuple[str, ...],
        validation_results: dict[str, bool],
    ) -> ConnectorCommand:
        state = self.status()
        if not state["authorized"]:
            raise PermissionError("live activation requires explicit owner approval")
        if task.repository not in self.policy.repository_allowlist:
            raise PermissionError("repository is not approved for live activation")
        if self.policy.max_draft_prs_per_cycle < 1:
            raise PermissionError("draft PR creation is disabled by cycle limit")

        plan = self.executor.plan(task)
        package = self.executor.build_draft_pr_package(
            task,
            plan,
            changed_paths,
            validation_results,
        )
        return ConnectorCommand(
            operation="create_draft_pull_request",
            repository=task.repository,
            branch_name=package.branch_name,
            title=package.title,
            body=package.body,
            draft=True,
        )
