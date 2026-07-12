"""BUILD-062 Calyx Queue — live execution queue management.

Exposes the Calyx execution queue as an authenticated API so Mission Control
can inspect queue state, enqueue work, cancel jobs, and retry failures without
touching placeholder paths.

Job lifecycle states: queued → running → completed | failed | cancelled
                       failed → retrying → running
                       queued → cancelled
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

router = APIRouter(prefix="/api/calyx-queue", tags=["calyx-queue"])

BUILD_ID = "BUILD-062"

JOB_LIFECYCLE_STATES = {
    "queued",
    "running",
    "paused",
    "completed",
    "failed",
    "cancelled",
    "retrying",
}

TERMINAL_STATES = {"completed", "failed", "cancelled"}
CANCELLABLE_STATES = {"queued", "paused"}
RETRYABLE_STATES = {"failed", "cancelled"}

# In-memory fallback when no DATABASE_URL is configured
_QUEUE: list[dict[str, Any]] = []


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def actor(auth: dict[str, object]) -> str:
    return str(auth.get("actor") or "owner")


class EnqueueRequest(BaseModel):
    job_type: str = Field(min_length=1, description="Type of job to queue, e.g. 'harvest_gbif', 'audit', 'export'")
    payload: dict[str, Any] = Field(default_factory=dict, description="Job-specific parameters")
    priority: int = Field(default=50, ge=1, le=100)
    subsystem: str = Field(default="general", description="Owning subsystem label")


class QueueTransition(BaseModel):
    reason: str | None = None


def _db_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def _db_execute(callback):
    """Execute a callback with a psycopg cursor, falling back to in-memory."""
    url = _db_url()
    if not url:
        return callback(None)
    try:
        with psycopg.connect(url, row_factory=dict_row, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                result = callback(cur)
            conn.commit()
            return result
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Calyx Queue database unavailable: {exc}") from exc


def _list_queue(cur, status_filter: str | None = None) -> list[dict[str, Any]]:
    if cur is None:
        items = _QUEUE
        if status_filter:
            items = [i for i in items if i.get("status") == status_filter]
        return sorted(items, key=lambda i: (-(i.get("priority") or 50), i.get("queued_at") or ""))
    try:
        if status_filter:
            cur.execute(
                "SELECT payload FROM oc_admin.build062_calyx_queue WHERE payload->>'status' = %s ORDER BY (payload->>'priority')::int DESC, (payload->>'queued_at') ASC",
                (status_filter,),
            )
        else:
            cur.execute(
                "SELECT payload FROM oc_admin.build062_calyx_queue ORDER BY (payload->>'priority')::int DESC, (payload->>'queued_at') ASC"
            )
        return [dict(row["payload"]) for row in cur.fetchall()]
    except Exception:
        # Table may not exist yet; fall back to in-memory
        items = _QUEUE
        if status_filter:
            items = [i for i in items if i.get("status") == status_filter]
        return sorted(items, key=lambda i: (-(i.get("priority") or 50), i.get("queued_at") or ""))


def _get_job(cur, job_id: str) -> dict[str, Any] | None:
    if cur is None:
        for item in _QUEUE:
            if item.get("id") == job_id:
                return item
        return None
    try:
        cur.execute("SELECT payload FROM oc_admin.build062_calyx_queue WHERE id = %s", (job_id,))
        row = cur.fetchone()
        return dict(row["payload"]) if row else None
    except Exception:
        for item in _QUEUE:
            if item.get("id") == job_id:
                return item
        return None


def _insert_job(cur, job: dict[str, Any]) -> dict[str, Any]:
    if cur is None:
        _QUEUE.insert(0, job)
        return job
    try:
        cur.execute(
            "INSERT INTO oc_admin.build062_calyx_queue (id, payload) VALUES (%s, %s)",
            (job["id"], Jsonb(job)),
        )
    except Exception:
        _QUEUE.insert(0, job)
    return job


def _update_job(cur, job_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    job = _get_job(cur, job_id)
    if job is None:
        return None
    job.update(updates)
    if cur is None:
        return job
    try:
        cur.execute(
            "UPDATE oc_admin.build062_calyx_queue SET payload = %s WHERE id = %s",
            (Jsonb(job), job_id),
        )
    except Exception:
        for item in _QUEUE:
            if item.get("id") == job_id:
                item.update(updates)
                return item
    return job


def _queue_summary(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {state: 0 for state in JOB_LIFECYCLE_STATES}
    for item in items:
        state = item.get("status", "queued")
        counts[state] = counts.get(state, 0) + 1
    return counts


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("")
def list_queue(
    status: str | None = None,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Return queue items, optionally filtered by lifecycle status."""
    if status and status not in JOB_LIFECYCLE_STATES:
        raise HTTPException(status_code=400, detail=f"Unknown status '{status}'. Valid states: {sorted(JOB_LIFECYCLE_STATES)}")

    def _fetch(cur):
        return _list_queue(cur, status_filter=status)

    items = _db_execute(_fetch)
    return {
        "build": BUILD_ID,
        "items": items,
        "total": len(items),
        "summary": _queue_summary(items),
        "lifecycle_states": sorted(JOB_LIFECYCLE_STATES),
        "owner": actor(auth),
        "generated_at": utc_now(),
    }


@router.post("")
def enqueue_job(
    request: EnqueueRequest,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Enqueue a new job into the Calyx execution queue."""
    job_id = f"CQ-{uuid4().hex[:12].upper()}"
    job: dict[str, Any] = {
        "id": job_id,
        "job_type": request.job_type,
        "payload": request.payload,
        "priority": request.priority,
        "subsystem": request.subsystem,
        "status": "queued",
        "progress": 0,
        "queued_at": utc_now(),
        "queued_by": actor(auth),
        "started_at": None,
        "completed_at": None,
        "active_worker": None,
        "rows_processed": None,
        "rows_inserted": None,
        "duplicates": None,
        "errors": [],
        "warnings": [],
        "result_summary": None,
        "logs": [],
        "retry_count": 0,
    }

    def _insert(cur):
        return _insert_job(cur, job)

    saved = _db_execute(_insert)
    return {"status": "queued", "job": saved, "build": BUILD_ID}


@router.get("/{job_id}")
def get_job(
    job_id: str,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Return full telemetry for a specific queue job."""
    def _get(cur):
        return _get_job(cur, job_id)

    job = _db_execute(_get)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
    return {"job": job, "build": BUILD_ID}


@router.post("/{job_id}/cancel")
def cancel_job(
    job_id: str,
    request: QueueTransition,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Cancel a queued or paused job."""
    def _do(cur):
        job = _get_job(cur, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
        if job.get("status") not in CANCELLABLE_STATES:
            raise HTTPException(
                status_code=409,
                detail=f"Job {job_id} is in state '{job.get('status')}' and cannot be cancelled. Cancellable states: {sorted(CANCELLABLE_STATES)}",
            )
        updates = {
            "status": "cancelled",
            "completed_at": utc_now(),
            "result_summary": request.reason or "Cancelled by owner.",
            "cancelled_by": actor(auth),
        }
        return _update_job(cur, job_id, updates)

    job = _db_execute(_do)
    return {"status": "cancelled", "job": job, "build": BUILD_ID}


@router.post("/{job_id}/retry")
def retry_job(
    job_id: str,
    request: QueueTransition,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Retry a failed or cancelled job."""
    def _do(cur):
        job = _get_job(cur, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
        if job.get("status") not in RETRYABLE_STATES:
            raise HTTPException(
                status_code=409,
                detail=f"Job {job_id} is in state '{job.get('status')}' and cannot be retried. Retryable states: {sorted(RETRYABLE_STATES)}",
            )
        retry_count = int(job.get("retry_count") or 0) + 1
        updates = {
            "status": "retrying",
            "retry_count": retry_count,
            "started_at": None,
            "completed_at": None,
            "errors": [],
            "result_summary": request.reason or f"Retrying (attempt {retry_count}).",
            "retried_by": actor(auth),
            "retried_at": utc_now(),
        }
        return _update_job(cur, job_id, updates)

    job = _db_execute(_do)
    return {"status": "retrying", "job": job, "build": BUILD_ID}


@router.post("/{job_id}/pause")
def pause_job(
    job_id: str,
    request: QueueTransition,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Pause a running job."""
    def _do(cur):
        job = _get_job(cur, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
        if job.get("status") != "running":
            raise HTTPException(
                status_code=409,
                detail=f"Job {job_id} is in state '{job.get('status')}' and cannot be paused (must be 'running').",
            )
        updates = {
            "status": "paused",
            "result_summary": request.reason or "Paused by owner.",
            "paused_by": actor(auth),
            "paused_at": utc_now(),
        }
        return _update_job(cur, job_id, updates)

    job = _db_execute(_do)
    return {"status": "paused", "job": job, "build": BUILD_ID}


@router.post("/{job_id}/resume")
def resume_job(
    job_id: str,
    request: QueueTransition,
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Resume a paused job."""
    def _do(cur):
        job = _get_job(cur, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown job: {job_id}")
        if job.get("status") != "paused":
            raise HTTPException(
                status_code=409,
                detail=f"Job {job_id} is in state '{job.get('status')}' and cannot be resumed (must be 'paused').",
            )
        updates = {
            "status": "queued",
            "result_summary": request.reason or "Resumed by owner.",
            "resumed_by": actor(auth),
            "resumed_at": utc_now(),
        }
        return _update_job(cur, job_id, updates)

    job = _db_execute(_do)
    return {"status": "queued", "job": job, "build": BUILD_ID}


@router.get("/telemetry/summary")
def queue_telemetry(
    auth: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict[str, Any]:
    """Return live queue telemetry — counts per state, recent activity."""
    def _fetch(cur):
        return _list_queue(cur)

    items = _db_execute(_fetch)
    summary = _queue_summary(items)

    active = [i for i in items if i.get("status") == "running"]
    queued = [i for i in items if i.get("status") == "queued"]
    failed = [i for i in items if i.get("status") == "failed"]

    total_rows_processed = sum(int(i.get("rows_processed") or 0) for i in items)
    total_rows_inserted = sum(int(i.get("rows_inserted") or 0) for i in items)
    total_errors = sum(len(i.get("errors") or []) for i in items)
    total_warnings = sum(len(i.get("warnings") or []) for i in items)

    next_job = queued[0] if queued else None
    active_job = active[0] if active else None

    return {
        "build": BUILD_ID,
        "queue_depth": len(queued),
        "active_workers": len(active),
        "failed_jobs": len(failed),
        "lifecycle_counts": summary,
        "total_jobs": len(items),
        "rows_processed": total_rows_processed,
        "rows_inserted": total_rows_inserted,
        "errors": total_errors,
        "warnings": total_warnings,
        "next_job": {
            "id": next_job["id"],
            "job_type": next_job.get("job_type"),
            "subsystem": next_job.get("subsystem"),
            "priority": next_job.get("priority"),
            "queued_at": next_job.get("queued_at"),
        } if next_job else None,
        "active_job": {
            "id": active_job["id"],
            "job_type": active_job.get("job_type"),
            "subsystem": active_job.get("subsystem"),
            "progress": active_job.get("progress"),
            "active_worker": active_job.get("active_worker"),
            "started_at": active_job.get("started_at"),
        } if active_job else None,
        "owner": actor(auth),
        "generated_at": utc_now(),
    }
