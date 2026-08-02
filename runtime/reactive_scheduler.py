"""Governed scheduler for Calyx Reactive Mode.

The scheduler evaluates whether a read-only audit cycle may run. It does not
perform merges, deployments, publication, deletion, external communication,
or governance changes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass(frozen=True)
class SchedulerPolicy:
    enabled: bool = False
    owner_approved: bool = False
    interval_minutes: int = 60
    max_tasks_per_cycle: int = 10

    def validated(self) -> SchedulerPolicy:
        if not 15 <= self.interval_minutes <= 1440:
            raise ValueError("interval_minutes must be between 15 and 1440")
        if not 0 <= self.max_tasks_per_cycle <= 50:
            raise ValueError("max_tasks_per_cycle must be between 0 and 50")
        return self


class ReactiveScheduler:
    def __init__(self, policy: SchedulerPolicy) -> None:
        self.policy = policy.validated()
        self.last_run_at: datetime | None = None

    def status(self, now: datetime | None = None) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        authorized = self.policy.enabled and self.policy.owner_approved
        due = authorized and (
            self.last_run_at is None
            or current - self.last_run_at >= timedelta(minutes=self.policy.interval_minutes)
        )
        return {
            "enabled": self.policy.enabled,
            "owner_approved": self.policy.owner_approved,
            "authorized": authorized,
            "due": due,
            "mode": "reactive_read_only",
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_publication": False,
        }

    def run_if_due(
        self,
        cycle: Callable[[int], dict[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = now or datetime.now(timezone.utc)
        state = self.status(current)
        if not state["due"]:
            return {"executed": False, "reason": "disabled_not_approved_or_not_due", **state}

        result = cycle(self.policy.max_tasks_per_cycle)
        self.last_run_at = current
        return {"executed": True, "result": result, **self.status(current)}
