from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.database import get_session_local


def run_once(policy: ProgramAutonomyPolicy | None = None) -> dict[str, Any]:
    active_policy = (policy or ProgramAutonomyPolicy.from_environ()).validated()
    state = active_policy.status()
    if not state["authorized"]:
        return {
            "executed": False,
            "reason": "disabled_or_owner_not_configured",
            "policy": state,
        }

    SessionLocal = get_session_local()
    with SessionLocal() as db:
        result = run_deterministic_program_cycle(
            db,
            owner=active_policy.owner,
            worker_id=active_policy.worker_id,
            max_jobs=active_policy.max_jobs_per_cycle,
            lease_seconds=active_policy.lease_seconds,
            timeout_seconds=active_policy.timeout_seconds,
        )
    return {"executed": True, "policy": state, "cycle": result.as_dict()}


def run_forever(
    policy: ProgramAutonomyPolicy | None = None,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    on_cycle: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    active_policy = (policy or ProgramAutonomyPolicy.from_environ()).validated()
    if not active_policy.status()["authorized"]:
        raise PermissionError("PROGRAM_AUTONOMY_NOT_AUTHORIZED")

    while True:
        result = run_once(active_policy)
        if on_cycle is not None:
            on_cycle(result)
        sleeper(active_policy.poll_seconds)


def main() -> int:
    policy = ProgramAutonomyPolicy.from_environ()
    if not policy.status()["authorized"]:
        print(json.dumps({"worker": "calyx-program-autonomy", "policy": policy.status()}, sort_keys=True))
        return 0

    def emit(result: dict[str, Any]) -> None:
        print(json.dumps(result, sort_keys=True, default=str), flush=True)

    run_forever(policy, on_cycle=emit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
