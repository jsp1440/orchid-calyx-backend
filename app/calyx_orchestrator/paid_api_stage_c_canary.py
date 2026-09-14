"""Bounded real-provider Stage C canary through the canonical BoundedDispatcher.

This module does nothing on import.  Running it requires an explicitly configured paid
provider key and remains hard-capped by PaidAPIBudgetGovernor.  It performs analysis
only: no repository mutation, merge, deployment, publication, or production action.
"""

from __future__ import annotations

import argparse
import json
import threading
from dataclasses import dataclass
from typing import Any

from .bounded_dispatcher import BoundedDispatcher, DispatchConfig
from .deep_orchestrate import AUTH_WORKSPACE, DeepOrchestrate, Priority, TaskLeaf, TaskState
from .github_coding_executor import BudgetClass, ConvergenceClass
from .paid_api_worker import PaidAPIWorker, build_paid_api_worker_from_env

FAKE_BASE_SHA = "a" * 40
DEFAULT_CEILING_USD = 50.0


def _canary_leaf(index: int) -> TaskLeaf:
    key = f"stage-c-real-canary:{index}"
    leaf = TaskLeaf(
        key=key,
        title=f"Stage C real canonical-dispatch canary lane {index}",
        repo="orchid-calyx-backend",
        module="app/calyx_orchestrator",
        priority=Priority.P0,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
        acceptance_criteria=[
            "provider analysis returns through BoundedDispatcher",
            "budget receipt is persisted as task evidence",
            "task reaches canonical terminal state",
        ],
    )
    leaf.evidence = {
        "mission_id": key,
        "repository": "jsp1440/orchid-calyx-backend",
        "objective": (
            "Inspect the Orchid Continuum canonical dispatcher/paid-worker integration "
            "and return a concise validation plan. Do not modify code or perform any "
            "merge, deploy, publication, credential, taxonomy, or production action."
        ),
        "acceptance_criteria": ["analysis-only response", "bounded cost receipt"],
        "validation_commands": ["no repository mutation; canary only"],
        "budget_class": BudgetClass.TINY.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": FAKE_BASE_SHA,
    }
    return leaf


@dataclass
class ConcurrencyProbeWorker:
    """Observe canonical LEASED state and synchronize real provider calls."""

    inner: PaidAPIWorker
    width: int

    def __post_init__(self) -> None:
        self._barrier = threading.Barrier(self.width)
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.leased_seen: list[str] = []

    def execute(self, leaf: TaskLeaf):
        if leaf.state is not TaskState.LEASED:
            raise RuntimeError(f"CANARY_NOT_LEASED: {leaf.key} state={leaf.state.value}")
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.leased_seen.append(leaf.key)
        try:
            self._barrier.wait(timeout=10)
            return self.inner.execute(leaf)
        finally:
            with self._lock:
                self.active -= 1


def run_stage_c_canary(*, lanes: int = 2, ceiling_usd: float = DEFAULT_CEILING_USD) -> dict[str, Any]:
    if lanes < 2 or lanes > 8:
        raise ValueError("lanes must be between 2 and 8")
    if ceiling_usd <= 0 or ceiling_usd > DEFAULT_CEILING_USD:
        raise ValueError(f"ceiling_usd must be >0 and <= {DEFAULT_CEILING_USD}")

    reservoir = DeepOrchestrate(configured_width=lanes)
    keys = [f"stage-c-real-canary:{index}" for index in range(1, lanes + 1)]
    reservoir.register_many([_canary_leaf(index) for index in range(1, lanes + 1)])

    paid_worker, governor = build_paid_api_worker_from_env(ceiling_usd=ceiling_usd)
    probe = ConcurrencyProbeWorker(inner=paid_worker, width=lanes)
    result = BoundedDispatcher(reservoir, worker=probe).run(
        DispatchConfig(
            max_tasks=lanes,
            max_iterations=2,
            width=lanes,
            lease_holder="stage-c-real-canary",
        )
    )

    tasks = [reservoir.get(key) for key in keys]
    evidence = {
        task.key: {
            "state": task.state.value,
            "provider": task.evidence.get("provider"),
            "model": task.evidence.get("model"),
            "run_id": task.evidence.get("run_id"),
            "actual_usd": task.evidence.get("actual_usd"),
            "receipt_ledger_line": task.evidence.get("receipt_ledger_line"),
        }
        for task in tasks
    }
    actual_spend = sum(float(item.get("actual_usd") or 0.0) for item in evidence.values())
    all_completed = all(task.state is TaskState.COMPLETED for task in tasks)

    report = {
        "stage": "C_REAL_CANONICAL_DISPATCH",
        "pass": bool(
            all_completed
            and result.tasks_executed == lanes
            and probe.max_active == lanes
            and len(probe.leased_seen) == lanes
            and reservoir.active_tasks() == []
        ),
        "lanes_requested": lanes,
        "tasks_executed": result.tasks_executed,
        "max_simultaneous_leased_workers": probe.max_active,
        "leased_keys_seen": sorted(probe.leased_seen),
        "terminal_summary": result.summary(),
        "active_tasks_after": [task.key for task in reservoir.active_tasks()],
        "actual_spend_usd": round(actual_spend, 8),
        "program_ceiling_usd": ceiling_usd,
        "governor_spent_usd": round(governor.spent_usd, 8),
        "governor_reserved_usd": round(governor.reserved_usd, 8),
        "tasks": evidence,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded Stage C real-provider canonical dispatch canary")
    parser.add_argument("--lanes", type=int, default=2)
    parser.add_argument("--ceiling", type=float, default=DEFAULT_CEILING_USD)
    args = parser.parse_args()

    report = run_stage_c_canary(lanes=args.lanes, ceiling_usd=args.ceiling)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
