from __future__ import annotations

from app.calyx_orchestrator.github_agent_bounded_supervisor import (
    SupervisorStopReason,
    run_bounded_dispatch_supervisor,
)
from app.calyx_orchestrator.github_agent_dispatch_cycle import DispatchCycleResult


class FakeCycle:
    def __init__(self, results: list[DispatchCycleResult]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def run_once(self, *, owner: str, execute: bool = False, confirmation: str | None = None) -> DispatchCycleResult:
        self.calls.append({"owner": owner, "execute": execute, "confirmation": confirmation})
        return self.results.pop(0)


def test_supervisor_is_preflight_only_by_default_and_stops_after_one_ready_candidate() -> None:
    cycle = FakeCycle([DispatchCycleResult(state="preflight_ready", program_job_id="job-1")])

    result = run_bounded_dispatch_supervisor(cycle, owner="owner")

    assert result.stop_reason is SupervisorStopReason.PREFLIGHT_ONLY
    assert result.cycles_attempted == 1
    assert cycle.calls == [{"owner": "owner", "execute": False, "confirmation": None}]


def test_supervisor_stops_deterministically_when_queue_is_idle() -> None:
    cycle = FakeCycle([DispatchCycleResult(state="idle_no_candidate")])

    result = run_bounded_dispatch_supervisor(cycle, owner="owner", max_cycles=5, execute=True, confirmation="token")

    assert result.stop_reason is SupervisorStopReason.IDLE
    assert result.cycles_attempted == 1


def test_supervisor_stops_on_owner_review_without_consuming_later_cycles() -> None:
    cycle = FakeCycle(
        [
            DispatchCycleResult(state="awaiting_owner", action="owner_review", program_job_id="job-1"),
            DispatchCycleResult(state="idle_no_candidate"),
        ]
    )

    result = run_bounded_dispatch_supervisor(cycle, owner="owner", max_cycles=5, execute=True, confirmation="token")

    assert result.stop_reason is SupervisorStopReason.OWNER_REVIEW
    assert result.cycles_attempted == 1
    assert len(cycle.calls) == 1


def test_supervisor_never_exceeds_hard_cycle_limit_and_emits_receipts() -> None:
    cycle = FakeCycle(
        [
            DispatchCycleResult(state="agent_assigned", action="agent_assigned", program_job_id=f"job-{index}")
            for index in range(1, 4)
        ]
    )

    result = run_bounded_dispatch_supervisor(cycle, owner="owner", max_cycles=3, execute=True, confirmation="token")

    assert result.stop_reason is SupervisorStopReason.MAX_CYCLES
    assert result.cycles_attempted == 3
    assert [receipt.cycle_number for receipt in result.receipts] == [1, 2, 3]
    assert [receipt.program_job_id for receipt in result.receipts] == ["job-1", "job-2", "job-3"]
    assert len(cycle.calls) == 3


def test_supervisor_rejects_non_positive_cycle_limit_before_dispatch() -> None:
    cycle = FakeCycle([])

    try:
        run_bounded_dispatch_supervisor(cycle, owner="owner", max_cycles=0)
    except ValueError as exc:
        assert str(exc) == "GITHUB_CODING_SUPERVISOR_MAX_CYCLES_POSITIVE"
    else:
        raise AssertionError("expected ValueError")

    assert cycle.calls == []
