from __future__ import annotations

import json
import os
import time
from collections.abc import Callable

from app.database import get_session_local

from .completion_scheduler import EngineeringCompletionScheduler
from .github import GitHubEngineeringClient
from .service import CalyxEngineeringService

DEFAULT_WORKER_ID = "calyx-engineering-completion"


def runtime_ready() -> bool:
    return CalyxEngineeringService.enabled() and bool(os.getenv("GITHUB_TOKEN", "").strip())


def run_once(*, worker_id: str = DEFAULT_WORKER_ID) -> dict:
    if not runtime_ready():
        return {"executed": False, "reason": "engineering_runtime_not_ready"}
    service = CalyxEngineeringService()
    client = GitHubEngineeringClient(service.repository)
    SessionLocal = get_session_local()
    with SessionLocal() as db:
        return EngineeringCompletionScheduler(db, client).run_once(worker_id=worker_id)


def run_forever(
    *,
    worker_id: str = DEFAULT_WORKER_ID,
    sleeper: Callable[[float], None] = time.sleep,
    on_cycle: Callable[[dict], None] | None = None,
) -> None:
    poll_seconds = max(
        10,
        min(int(os.getenv("CALYX_ENGINEERING_COMPLETION_WORKER_SECONDS", "30")), 900),
    )
    while True:
        result = run_once(worker_id=worker_id)
        if on_cycle is not None:
            on_cycle(result)
        sleeper(poll_seconds)


def main() -> int:
    worker_id = os.getenv("CALYX_ENGINEERING_COMPLETION_WORKER_ID", DEFAULT_WORKER_ID).strip()
    if not worker_id:
        worker_id = DEFAULT_WORKER_ID

    def emit(result: dict) -> None:
        print(json.dumps(result, sort_keys=True, default=str), flush=True)

    if not runtime_ready():
        emit({"worker": worker_id, "executed": False, "reason": "engineering_runtime_not_ready"})
        return 0
    run_forever(worker_id=worker_id, on_cycle=emit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
