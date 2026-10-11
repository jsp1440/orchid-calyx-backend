from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.executor_registry import AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_cycle import (
    ZERO_EXECUTION_CATEGORIES,
    run_deterministic_program_cycle,
)
from app.database import get_session_local

logger = logging.getLogger(__name__)

#: Optional upstream step run at the start of every scheduled cycle, before the
#: worker claims. It is the Brain work-selection/replenishment pulse: it selects
#: eligible work and submits it through the canonical authenticated handoff
#: (``POST /brain/canonical/builds/submit``). It returns a JSON-safe record; a
#: zero-submission pulse names its reason as ``zero_reason`` using
#: ``ZERO_EXECUTION_CATEGORIES``. It never claims, executes or settles jobs.
Replenisher = Callable[[], dict[str, Any]]

# Upstream reasons that explain an idle cycle better than "no eligible work".
_UPSTREAM_REASONS = frozenset(ZERO_EXECUTION_CATEGORIES) - {"no_eligible_work"}


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _replenish(replenish: Replenisher | None) -> dict[str, Any] | None:
    if replenish is None:
        return None
    try:
        record = replenish()
    except Exception as exc:  # replenishment must not stop the claim/execute step
        logger.exception("program autonomy replenishment failed")
        return {"error": {"exception_type": type(exc).__name__}}
    if not isinstance(record, dict):
        return {"error": {"exception_type": "ReplenishmentRecordInvalid"}}
    return record


def classify_cycle(
    cycle: dict[str, Any] | None,
    replenishment: dict[str, Any] | None,
    *,
    reason: str | None = None,
) -> dict[str, Any]:
    """Truthful per-cycle accounting: productive, healthy waiting or defect."""
    if cycle is not None and int(cycle.get("productive_jobs") or 0) > 0:
        return {"productive": True, "category": None, "healthy": True}
    if reason == "disabled_or_owner_not_configured":
        category = "owner_gate"
    elif reason == "cycle_failed" or cycle is None:
        category = "scheduler_defect"
    else:
        zero = cycle.get("zero_execution") or {}
        category = zero.get("category") or "scheduler_defect"
        upstream = (replenishment or {}).get("zero_reason")
        if (replenishment or {}).get("error") and category == "no_eligible_work":
            category = "scheduler_defect"
        elif category == "no_eligible_work" and upstream in _UPSTREAM_REASONS:
            category = upstream
    if category not in ZERO_EXECUTION_CATEGORIES:
        category = "scheduler_defect"
    return {
        "productive": False,
        "category": category,
        "healthy": ZERO_EXECUTION_CATEGORIES[category],
    }


def run_once(
    policy: ProgramAutonomyPolicy | None = None,
    *,
    replenish: Replenisher | None = None,
    registry: AuthoritativeExecutorRegistry | None = None,
) -> dict[str, Any]:
    active_policy = (policy or ProgramAutonomyPolicy.from_environ()).validated()
    state = active_policy.status()
    started_at = _now()
    if not state["authorized"]:
        return {
            "executed": False,
            "reason": "disabled_or_owner_not_configured",
            "policy": state,
            "started_at": started_at,
            "classification": classify_cycle(
                None, None, reason="disabled_or_owner_not_configured"
            ),
        }

    replenishment = _replenish(replenish)
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        result = run_deterministic_program_cycle(
            db,
            owner=active_policy.owner,
            worker_id=active_policy.worker_id,
            max_jobs=active_policy.max_jobs_per_cycle,
            lease_seconds=active_policy.lease_seconds,
            timeout_seconds=active_policy.timeout_seconds,
            registry=registry,
        )
    cycle = result.as_dict()
    return {
        "executed": True,
        "policy": state,
        "started_at": started_at,
        "finished_at": _now(),
        "replenishment": replenishment,
        "cycle": cycle,
        "classification": classify_cycle(cycle, replenishment),
    }


def run_forever(
    policy: ProgramAutonomyPolicy | None = None,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    on_cycle: Callable[[dict[str, Any]], None] | None = None,
    replenish: Replenisher | None = None,
    registry: AuthoritativeExecutorRegistry | None = None,
) -> None:
    active_policy = (policy or ProgramAutonomyPolicy.from_environ()).validated()
    if not active_policy.status()["authorized"]:
        raise PermissionError("PROGRAM_AUTONOMY_NOT_AUTHORIZED")

    sequence = 0
    while True:
        sequence += 1
        try:
            result = run_once(active_policy, replenish=replenish, registry=registry)
        except Exception as exc:  # one bad cycle must not end the loop
            # Logged with its traceback, reported to on_cycle, then the loop
            # sleeps and continues. BaseException (KeyboardInterrupt,
            # SystemExit) still stops the worker.
            logger.exception("program autonomy cycle failed")
            result = {
                "executed": False,
                "reason": "cycle_failed",
                "error": {"exception_type": type(exc).__name__},
                "classification": classify_cycle(None, None, reason="cycle_failed"),
            }
        result["scheduler"] = {
            "sequence": sequence,
            "worker_id": active_policy.worker_id,
            "poll_seconds": active_policy.poll_seconds,
        }
        if on_cycle is not None:
            on_cycle(result)
        sleeper(active_policy.poll_seconds)


def main() -> int:
    policy = ProgramAutonomyPolicy.from_environ()
    if not policy.status()["authorized"]:
        print(
            json.dumps(
                {"worker": "calyx-program-autonomy", "policy": policy.status()},
                sort_keys=True,
            )
        )
        return 0

    def emit(result: dict[str, Any]) -> None:
        print(json.dumps(result, sort_keys=True, default=str), flush=True)

    run_forever(policy, on_cycle=emit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
