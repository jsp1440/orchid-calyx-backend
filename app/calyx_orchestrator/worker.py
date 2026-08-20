from __future__ import annotations

import os
import socket
import time

from app.calyx_engineering.completion_scheduler import EngineeringCompletionScheduler
from app.calyx_engineering.github import GitHubEngineeringClient
from app.calyx_engineering.service import CalyxEngineeringService
from app.database import get_session_local

from .service import CalyxOrchestrator


def enabled() -> bool:
    return (
        os.getenv("CALYX_ORCHESTRATOR_ENABLED", "false").strip().casefold() == "true"
        and os.getenv("CALYX_ORCHESTRATOR_MODE", "").strip().casefold() == "preproduction"
    )


def engineering_enabled() -> bool:
    return CalyxEngineeringService.enabled()


def worker_enabled() -> bool:
    return enabled() or engineering_enabled()


def run_cycle(db, *, worker_id: str, lease_seconds: int) -> str:
    """Run at most one persisted job from each explicitly enabled lane."""
    if enabled():
        orchestrator = CalyxOrchestrator(db)
        job = orchestrator.claim(worker_id=worker_id, lease_seconds=lease_seconds)
        if job is not None:
            token = job.lease_token
            if token is None:
                raise RuntimeError("CLAIMED_JOB_WITHOUT_LEASE_TOKEN")
            orchestrator.execute(job, worker_id=worker_id, lease_token=token)
            return "orchestrator_job"

    if engineering_enabled():
        service = CalyxEngineeringService()
        scheduler = EngineeringCompletionScheduler(
            db,
            GitHubEngineeringClient(service.repository),
        )
        result = scheduler.run_once(
            worker_id=f"{worker_id}:engineering",
            lease_seconds=lease_seconds,
        )
        if result.get("executed"):
            return "engineering_completion_job"

    return "idle"


def run_forever() -> None:
    if not worker_enabled():
        raise SystemExit(
            "Calyx durable worker is disabled. Enable the orchestrator or the governed "
            "engineering completion lane in preproduction mode."
        )
    worker_id = os.getenv("CALYX_WORKER_ID", f"{socket.gethostname()}-{os.getpid()}")
    poll_seconds = max(2, int(os.getenv("CALYX_ORCHESTRATOR_POLL_SECONDS", "10")))
    lease_seconds = max(60, int(os.getenv("CALYX_ORCHESTRATOR_LEASE_SECONDS", "300")))
    SessionLocal = get_session_local()
    while True:
        db = SessionLocal()
        try:
            outcome = run_cycle(db, worker_id=worker_id, lease_seconds=lease_seconds)
            if outcome == "idle":
                time.sleep(poll_seconds)
        except Exception as exc:  # noqa: BLE001 -- durable worker must survive unexpected job failures
            db.rollback()
            print(f"[CALYX-ORCHESTRATOR] worker error: {type(exc).__name__}")
            time.sleep(poll_seconds)
        finally:
            db.close()


if __name__ == "__main__":
    run_forever()
