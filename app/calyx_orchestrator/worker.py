from __future__ import annotations

import os
import socket
import time

from app.database import get_session_local

from .service import CalyxOrchestrator


def enabled() -> bool:
    return (
        os.getenv("CALYX_ORCHESTRATOR_ENABLED", "false").strip().casefold() == "true"
        and os.getenv("CALYX_ORCHESTRATOR_MODE", "").strip().casefold() == "preproduction"
    )


def run_forever() -> None:
    if not enabled():
        raise SystemExit(
            "Calyx orchestrator is disabled. Set CALYX_ORCHESTRATOR_ENABLED=true and "
            "CALYX_ORCHESTRATOR_MODE=preproduction to start the bounded worker."
        )
    worker_id = os.getenv("CALYX_WORKER_ID", f"{socket.gethostname()}-{os.getpid()}")
    poll_seconds = max(2, int(os.getenv("CALYX_ORCHESTRATOR_POLL_SECONDS", "10")))
    lease_seconds = max(60, int(os.getenv("CALYX_ORCHESTRATOR_LEASE_SECONDS", "300")))
    SessionLocal = get_session_local()
    while True:
        db = SessionLocal()
        try:
            orchestrator = CalyxOrchestrator(db)
            job = orchestrator.claim(worker_id=worker_id, lease_seconds=lease_seconds)
            if job is None:
                time.sleep(poll_seconds)
                continue
            token = job.lease_token
            if token is None:
                raise RuntimeError("CLAIMED_JOB_WITHOUT_LEASE_TOKEN")
            orchestrator.execute(job, worker_id=worker_id, lease_token=token)
        except Exception as exc:  # noqa: BLE001 -- durable worker must survive unexpected job failures
            db.rollback()
            print(f"[CALYX-ORCHESTRATOR] worker error: {type(exc).__name__}")
            time.sleep(poll_seconds)
        finally:
            db.close()


if __name__ == "__main__":
    run_forever()
