"""Owner-gated Mission Control commands for the governed Calyx worker."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from runtime.governed_worker_loop import GovernedWorkerLoop
from runtime.persistent_activation_state import (
    ActivationState,
    PersistentActivationController,
)


class RuntimeOperatorControls:
    """Expose bounded status, pause, resume, and run-once operations."""

    def __init__(
        self,
        controller: PersistentActivationController,
        worker: GovernedWorkerLoop,
    ) -> None:
        self._controller = controller
        self._worker = worker

    def status(self) -> dict[str, Any]:
        return {
            "activation": self._controller.load().as_dict(),
            "safety": self._worker.safety_status(),
        }

    def pause(self, *, owner_approved: bool) -> dict[str, Any]:
        self._require_owner(owner_approved)
        state = self._controller.load()
        return self._controller.save(replace(state, paused=True)).as_dict()

    def resume(self, *, owner_approved: bool) -> dict[str, Any]:
        self._require_owner(owner_approved)
        state = self._controller.load()
        return self._controller.save(
            replace(state, enabled=True, owner_approved=True, paused=False)
        ).as_dict()

    def run_once(self, *, owner_approved: bool) -> dict[str, Any]:
        self._require_owner(owner_approved)
        return self._worker.tick().as_dict()

    def configure(
        self,
        *,
        owner_approved: bool,
        interval_minutes: int,
        max_draft_prs_per_cycle: int = 1,
    ) -> dict[str, Any]:
        self._require_owner(owner_approved)
        current = self._controller.load()
        state = ActivationState(
            enabled=current.enabled,
            owner_approved=current.owner_approved,
            paused=current.paused,
            interval_minutes=interval_minutes,
            max_draft_prs_per_cycle=max_draft_prs_per_cycle,
            last_cycle_at=current.last_cycle_at,
            last_result=current.last_result,
            updated_at=current.updated_at,
        )
        return self._controller.save(state).as_dict()

    @staticmethod
    def _require_owner(owner_approved: bool) -> None:
        if not owner_approved:
            raise PermissionError("explicit owner approval is required")
