"""Deployment-safe governed worker loop for Calyx draft engineering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event
from time import sleep
from typing import Any

from runtime.persistent_activation_state import PersistentActivationController


@dataclass(frozen=True)
class WorkerTickResult:
    executed: bool
    reason: str
    cycle_result: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "executed": self.executed,
            "reason": self.reason,
            "cycle_result": self.cycle_result,
        }


class GovernedWorkerLoop:
    """Run owner-approved cycles while honoring persistent pause state."""

    def __init__(
        self,
        controller: PersistentActivationController,
        run_cycle: Callable[[], str],
        *,
        sleeper: Callable[[float], None] = sleep,
    ) -> None:
        self._controller = controller
        self._run_cycle = run_cycle
        self._sleeper = sleeper

    def tick(self) -> WorkerTickResult:
        state = self._controller.load()
        if not state.authorized:
            reason = "paused" if state.paused else "not-authorized"
            return WorkerTickResult(False, reason)

        result = self._run_cycle()
        self._controller.record_cycle(result)
        return WorkerTickResult(True, "cycle-complete", result)

    def run_forever(self, stop_event: Event) -> None:
        while not stop_event.is_set():
            state = self._controller.load()
            self.tick()
            stop_event.wait(state.interval_minutes * 60)

    @staticmethod
    def safety_status() -> dict[str, bool]:
        return {
            "automatic_merge": False,
            "automatic_deploy": False,
            "scientific_publication": False,
            "production_deletion": False,
            "external_communication": False,
            "permissions_change": False,
            "governance_change": False,
        }
