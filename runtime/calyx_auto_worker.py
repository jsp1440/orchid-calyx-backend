from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from app.calyx_orchestrator.auto_mission_service import AutoMissionCoordinator
from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy
from app.database import get_session_local


def run_once(policy: ProgramAutonomyPolicy | None = None) -> dict[str, Any]:
    active = (policy or ProgramAutonomyPolicy.from_environ()).validated()
    state = active.status()
    if not state["authorized"]:
        return {"executed": False, "reason": "disabled_or_owner_not_configured", "policy": state}
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        result = AutoMissionCoordinator(db).run_cycle(
            owner=active.owner,
            worker_id=active.worker_id,
            max_jobs=active.max_jobs_per_cycle,
            lease_seconds=max(active.lease_seconds, active.timeout_seconds),
            timeout_seconds=active.timeout_seconds,
        )
    return {"executed": True, "policy": state, "cycle": result.as_dict()}


def run_forever(
    policy: ProgramAutonomyPolicy | None = None,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    on_cycle: Callable[[dict[str, Any]], None] | None = None,
) -> None:
    active = (policy or ProgramAutonomyPolicy.from_environ()).validated()
    if not active.status()["authorized"]:
        raise PermissionError("PROGRAM_AUTONOMY_NOT_AUTHORIZED")
    while True:
        result = run_once(active)
        if on_cycle is not None:
            on_cycle(result)
        sleeper(active.poll_seconds)


def main() -> int:
    policy = ProgramAutonomyPolicy.from_environ()
    if not policy.status()["authorized"]:
        print(json.dumps({"worker": "calyx-auto-001", "policy": policy.status()}, sort_keys=True))
        return 0
    run_forever(
        policy,
        on_cycle=lambda result: print(json.dumps(result, sort_keys=True, default=str), flush=True),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
