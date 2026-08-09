from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.missions.repositories import PostgresMissionRepository
from app.performance_governance import CapacitySnapshot, PerformanceReadiness
from app.security import verify_owner_or_api_key

router = APIRouter(
    prefix="/brain/mission-control/performance",
    tags=["mission-control-performance"],
)
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _capacity_from_missions() -> CapacitySnapshot:
    telemetry = PostgresMissionRepository().telemetry()
    jobs = dict(telemetry.get("jobs_by_state") or {})
    worker = telemetry.get("worker_heartbeat") or {}
    active_workers = 1 if worker and str(worker.get("status") or "").lower() == "alive" else 0
    return CapacitySnapshot(
        queue_depth=int(telemetry.get("queue_depth") or 0),
        active_workers=active_workers,
        claimed_or_running_jobs=int(jobs.get("claimed", 0)) + int(jobs.get("running", 0)),
        retry_wait_jobs=int(jobs.get("retry_wait", 0)),
        dead_lettered_jobs=int(telemetry.get("dead_letter_jobs") or 0),
        source="oc_missions.telemetry",
    )


@router.get("/readiness")
def performance_readiness(identity: Identity) -> dict[str, Any]:
    _ = identity
    try:
        return PerformanceReadiness(_capacity_from_missions).snapshot()
    except (RuntimeError, OSError):
        return PerformanceReadiness().snapshot()
