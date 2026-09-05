from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .github_agent_dispatch_cycle import DispatchCycleResult, GitHubCodingAgentDispatchCycle


class SupervisorStopReason(str, Enum):
    MAX_CYCLES = "max_cycles"
    IDLE = "idle"
    OWNER_REVIEW = "owner_review"
    BLOCKED = "blocked"
    PREFLIGHT_ONLY = "preflight_only"


@dataclass(frozen=True, slots=True)
class SupervisorCycleReceipt:
    cycle_number: int
    state: str
    action: str | None
    reason: str | None
    program_job_id: str | None
    mission_id: str | None


@dataclass(frozen=True, slots=True)
class BoundedSupervisorResult:
    stop_reason: SupervisorStopReason
    cycles_attempted: int
    receipts: tuple[SupervisorCycleReceipt, ...]


class DispatchCycleLike(Protocol):
    def run_once(
        self,
        *,
        owner: str,
        execute: bool = False,
        confirmation: str | None = None,
    ) -> DispatchCycleResult: ...


def run_bounded_dispatch_supervisor(
    cycle: GitHubCodingAgentDispatchCycle | DispatchCycleLike,
    *,
    owner: str,
    max_cycles: int = 1,
    execute: bool = False,
    confirmation: str | None = None,
    stop_on_owner_review: bool = True,
) -> BoundedSupervisorResult:
    """Run a finite number of existing dispatch-cycle iterations.

    This function deliberately does not schedule itself, create workers, restore
    providers, or weaken the existing runtime policy. ``run_once`` remains the
    sole authority for owner/repository allowlists, budget classes, repair
    ceilings, execute confirmation, and all mutation side effects.

    The default is preflight-only and a single cycle, making invocation
    fail-closed unless the caller separately satisfies the existing execute
    contract.
    """

    if max_cycles <= 0:
        raise ValueError("GITHUB_CODING_SUPERVISOR_MAX_CYCLES_POSITIVE")

    receipts: list[SupervisorCycleReceipt] = []

    for cycle_number in range(1, max_cycles + 1):
        result = cycle.run_once(
            owner=owner,
            execute=execute,
            confirmation=confirmation,
        )
        receipts.append(
            SupervisorCycleReceipt(
                cycle_number=cycle_number,
                state=result.state,
                action=result.action,
                reason=result.reason,
                program_job_id=result.program_job_id,
                mission_id=result.mission_id,
            )
        )

        if not execute and result.state == "preflight_ready":
            return BoundedSupervisorResult(
                stop_reason=SupervisorStopReason.PREFLIGHT_ONLY,
                cycles_attempted=cycle_number,
                receipts=tuple(receipts),
            )

        if result.state == "idle_no_candidate":
            return BoundedSupervisorResult(
                stop_reason=SupervisorStopReason.IDLE,
                cycles_attempted=cycle_number,
                receipts=tuple(receipts),
            )

        if result.action == "owner_review" and stop_on_owner_review:
            return BoundedSupervisorResult(
                stop_reason=SupervisorStopReason.OWNER_REVIEW,
                cycles_attempted=cycle_number,
                receipts=tuple(receipts),
            )

        if result.state in {"rejected_admission", "blocked"} or result.action == "escalate":
            return BoundedSupervisorResult(
                stop_reason=SupervisorStopReason.BLOCKED,
                cycles_attempted=cycle_number,
                receipts=tuple(receipts),
            )

    return BoundedSupervisorResult(
        stop_reason=SupervisorStopReason.MAX_CYCLES,
        cycles_attempted=max_cycles,
        receipts=tuple(receipts),
    )
