"""Fail-closed supervised one-cycle pilot for Calyx.

The pilot prepares one reviewed draft-PR command package. It never executes
GitHub writes, merges, deployments, publication, deletion, communications,
permission changes, or governance changes.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any

from runtime.draft_engineering_executor import (
    EngineeringTask,
    GovernedDraftEngineeringExecutor,
)


@dataclass(frozen=True)
class SupervisedPilotResult:
    executed: bool
    reason: str
    package: dict[str, Any] | None = None

    def as_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True)


def pilot_enabled() -> bool:
    return os.getenv("CALYX_SUPERVISED_PILOT_ENABLED", "").strip().lower() == "true"


def approved_pilot_task() -> EngineeringTask | None:
    """Return the single owner-approved pilot task when explicitly enabled."""
    if not pilot_enabled():
        return None
    return EngineeringTask(
        task_key="audit-taxonomy-image-coverage-report",
        title="Add taxonomy-to-image coverage report",
        repository="jsp1440/orchid-calyx-backend",
        objective=(
            "Expose a read-only taxonomy-to-image coverage report using the canonical "
            "relationship integration layer."
        ),
        allowed_paths=(
            "runtime",
            "app/routers",
            "tests",
            "docs",
            ".github/workflows",
        ),
        risk="low",
        owner_approved=True,
    )


def run_supervised_pilot() -> str:
    """Prepare exactly one draft-only package and stop before connector execution."""
    task = approved_pilot_task()
    if task is None:
        return SupervisedPilotResult(False, "pilot-disabled").as_json()

    executor = GovernedDraftEngineeringExecutor()
    plan = executor.plan(task)
    package = executor.build_draft_pr_package(
        task,
        plan,
        changed_paths=("docs/CALYX-SUPERVISED-PILOT-001.md",),
        validation_results={
            "pilot-policy": True,
            "draft-only": True,
            "no-connector-execution": True,
        },
    )
    return SupervisedPilotResult(
        True,
        "draft-package-prepared-no-github-write",
        package=package.as_dict(),
    ).as_json()
