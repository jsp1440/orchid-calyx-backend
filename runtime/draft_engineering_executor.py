"""Governed autonomous draft-engineering execution contracts.

This module converts approved, low-risk queue tasks into bounded engineering
plans and draft pull-request packages. It cannot merge, deploy, publish,
change governance, or communicate externally beyond creating a draft PR.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Any, ClassVar


@dataclass(frozen=True)
class EngineeringTask:
    task_key: str
    title: str
    repository: str
    objective: str
    allowed_paths: tuple[str, ...]
    risk: str = "low"
    owner_approved: bool = False


@dataclass(frozen=True)
class EngineeringPlan:
    task_key: str
    branch_name: str
    allowed_paths: tuple[str, ...]
    validation_commands: tuple[str, ...]
    draft_only: bool
    prohibited_actions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DraftPullRequestPackage:
    title: str
    body: str
    branch_name: str
    base_branch: str
    draft: bool
    evidence: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GovernedDraftEngineeringExecutor:
    """Prepare bounded draft engineering work while failing closed."""

    supported_risks: ClassVar[set[str]] = {"low"}
    prohibited_actions: ClassVar[tuple[str, ...]] = (
        "merge",
        "deploy",
        "publish_scientific_knowledge",
        "delete_production_data",
        "send_external_communication",
        "change_permissions",
        "change_governance",
    )

    def plan(self, task: EngineeringTask) -> EngineeringPlan:
        self._validate_task(task)
        slug = self._slug(task.task_key)
        return EngineeringPlan(
            task_key=task.task_key,
            branch_name=f"calyx/draft/{slug}",
            allowed_paths=tuple(sorted(set(task.allowed_paths))),
            validation_commands=(
                "python -m ruff check .",
                "python -m pytest -q",
                "git diff --check",
            ),
            draft_only=True,
            prohibited_actions=self.prohibited_actions,
        )

    def validate_changed_paths(
        self,
        plan: EngineeringPlan,
        changed_paths: tuple[str, ...],
    ) -> None:
        allowed = tuple(PurePosixPath(path) for path in plan.allowed_paths)
        for changed in changed_paths:
            candidate = PurePosixPath(changed)
            if not any(
                candidate == root or root in candidate.parents for root in allowed
            ):
                raise PermissionError(f"path outside approved scope: {changed}")

    def build_draft_pr_package(
        self,
        task: EngineeringTask,
        plan: EngineeringPlan,
        changed_paths: tuple[str, ...],
        validation_results: dict[str, bool],
    ) -> DraftPullRequestPackage:
        self.validate_changed_paths(plan, changed_paths)
        failed = sorted(
            name for name, passed in validation_results.items() if not passed
        )
        if failed:
            raise RuntimeError(f"validation failed: {', '.join(failed)}")
        return DraftPullRequestPackage(
            title=f"CALYX DRAFT — {task.title}",
            body=(
                f"## Objective\n{task.objective}\n\n"
                "## Governance\n"
                "Prepared by the governed draft-engineering executor. "
                "Human review is required. Automatic merge and deployment are disabled.\n\n"
                f"## Changed paths\n{', '.join(changed_paths) or 'None'}"
            ),
            branch_name=plan.branch_name,
            base_branch="main",
            draft=True,
            evidence={
                "task_key": task.task_key,
                "changed_paths": list(changed_paths),
                "validation_results": validation_results,
                "prohibited_actions": list(plan.prohibited_actions),
            },
        )

    def _validate_task(self, task: EngineeringTask) -> None:
        if not task.owner_approved:
            raise PermissionError("owner approval is required")
        if task.risk not in self.supported_risks:
            raise PermissionError(f"unsupported autonomous risk: {task.risk}")
        if not task.allowed_paths:
            raise ValueError("at least one allowed path is required")
        if any(
            path.startswith("/") or ".." in PurePosixPath(path).parts
            for path in task.allowed_paths
        ):
            raise ValueError(
                "allowed paths must be repository-relative and traversal-free"
            )

    @staticmethod
    def _slug(value: str) -> str:
        normalized = "".join(
            char.lower() if char.isalnum() else "-" for char in value
        )
        slug = "-".join(part for part in normalized.split("-") if part)
        if not slug:
            raise ValueError("task key must contain letters or numbers")
        return slug[:64]
