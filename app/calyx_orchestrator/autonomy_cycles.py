"""Durable receipts for scheduled autonomy cycles and their read-only status.

``runtime.program_autonomy_worker.run_forever`` records one row per cycle.
Status separates three things that a bare heartbeat conflates:

* the scheduler is alive (``heartbeat.fresh``),
* work is being delivered (``last_productive``), and
* why it is not (the reason-coded category of non-productive cycles).

Nothing here is estimated: an owner with no recorded cycles reports
``no_cycles_recorded``, never a readiness figure.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .program_cycle import ZERO_EXECUTION_CATEGORIES
from .program_models import CalyxAutonomyCycle

#: A cycle may run its jobs for up to the execution timeout before the worker
#: sleeps again, so the heartbeat is stale only after two missed polls plus
#: this allowance.
HEARTBEAT_GRACE_SECONDS = 360
RECENT_WINDOW = 50


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _aware(datetime.fromisoformat(value))
    except ValueError:
        return None


def _replenishment_summary(record: object) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    if record.get("error"):
        return {"error": record["error"]}
    return {
        "zero_reason": record.get("zero_reason"),
        "detail": record.get("detail"),
        "submitted": [
            {"work_id": item.get("work_id"), "outcome": item.get("outcome")}
            for item in record.get("submissions") or []
            if isinstance(item, dict)
        ],
        "reconciled": [
            {"work_id": item.get("work_id"), "state": item.get("state")}
            for item in record.get("reconciled") or []
            if isinstance(item, dict)
        ],
        # Brain's per-state manifest counts and first undelivered items, so an
        # exhausted-but-undelivered run is diagnosable from the receipt alone.
        "manifest": record.get("manifest")
        if isinstance(record.get("manifest"), dict)
        else None,
        # P1 work-source reports (name, status, discovered, detail).
        "sources": record.get("sources")
        if isinstance(record.get("sources"), list)
        else None,
        # Continuous-loop stage counts (observers, generated, rejected,
        # proposals by state); bounded, no rationale text.
        "loop": _loop_summary(record.get("loop")),
        # Opt-in workspace refresh result (status, commits), when configured.
        "workspace_refresh": record.get("workspace_refresh")
        if isinstance(record.get("workspace_refresh"), dict)
        else None,
    }


def _loop_summary(loop: object) -> dict[str, Any] | None:
    if not isinstance(loop, dict):
        return None
    return {
        key: loop.get(key)
        for key in (
            "observers",
            "generated",
            "rejected",
            "proposals",
            "suppressed_origins",
            "submitted_candidates",
            "reconciled_undelivered",
            "approvals_error",
        )
        if loop.get(key) not in (None, [], {})
    }


def record_cycle(
    db: Session,
    result: dict[str, Any],
    *,
    owner: str,
    deployment_commit: str | None = None,
) -> str:
    """Persist one scheduled cycle result; returns the receipt id."""
    scheduler = result.get("scheduler") or {}
    classification = result.get("classification") or {}
    cycle = result.get("cycle") or {}
    category = classification.get("category")
    if category is not None and category not in ZERO_EXECUTION_CATEGORIES:
        category = "scheduler_defect"
    zero = cycle.get("zero_execution") or {}
    reason = zero.get("reason_code") or (result.get("reason") if not cycle else None)
    row = CalyxAutonomyCycle(
        owner=owner,
        worker_id=str(scheduler.get("worker_id") or "unknown"),
        sequence=int(scheduler.get("sequence") or 0),
        # The wait actually scheduled before the next cycle (idle backoff
        # included), so heartbeat staleness is judged against the real cadence.
        poll_seconds=int(
            scheduler.get("next_sleep_seconds") or scheduler.get("poll_seconds") or 0
        ),
        started_at=_parse(result.get("started_at")),
        finished_at=_parse(result.get("finished_at")) or datetime.now(UTC),
        productive=classification.get("productive") is True,
        category=category,
        healthy=classification.get("healthy") is True,
        completed_jobs=int(cycle.get("completed_jobs") or 0),
        productive_jobs=int(cycle.get("productive_jobs") or 0),
        failed_jobs=int(cycle.get("failed_jobs") or 0),
        reason_code=str(reason)[:160] if reason else None,
        job_keys_json=json.dumps(
            [
                item.get("job_key")
                for item in cycle.get("jobs") or []
                if item.get("productive")
            ]
        ),
        replenishment_json=(
            json.dumps(summary, sort_keys=True)
            if (summary := _replenishment_summary(result.get("replenishment")))
            else None
        ),
        deployment_commit=deployment_commit,
    )
    db.add(row)
    db.commit()
    return row.cycle_id


#: Brain pulse details that mean "the work supply has nothing new", mapped to
#: an explicit supply state. An empty queue is reported with its reason; it is
#: never evidence that the program is finished.
WORK_SUPPLY_STATES = {
    "WORK_MANIFEST_COMPLETED": "static_manifest_exhausted",
    "WORK_MANIFEST_EXHAUSTED_UNDELIVERED": "static_manifest_exhausted_undelivered",
    "WORK_MANIFEST_EMPTY": "static_manifest_empty",
    "WORK_SOURCES_DRAINED": "sources_drained",
    "WORK_SOURCES_IDLE": "sources_idle",
    "LOOP_NO_GAPS_DETECTED": "no_gaps_detected",
    "APPROVALS_UNREADABLE": "approvals_unreadable",
}
#: Continuous-loop details that carry a count or names after a colon.
WORK_SUPPLY_PREFIXES = {
    "AWAITING_APPROVAL": "awaiting_approval",
    "APPROVED_WORK_HAS_NO_EXECUTOR": "approved_work_has_no_executor",
    "RECONCILED_UNDELIVERED": "recent_work_undelivered",
    "ORIGINS_SUPPRESSED": "origins_suppressed",
}


def _consecutive_nonproductive(
    db: Session, *, owner: str, productive: CalyxAutonomyCycle | None
) -> int:
    """Exact count of non-productive cycles since the last productive one."""
    query = (
        select(func.count())
        .select_from(CalyxAutonomyCycle)
        .where(
            CalyxAutonomyCycle.owner == owner,
            CalyxAutonomyCycle.productive.is_(False),
        )
    )
    if productive is not None:
        query = query.where(CalyxAutonomyCycle.finished_at > productive.finished_at)
    return int(db.scalar(query) or 0)


def _idle_view(
    db: Session,
    latest: CalyxAutonomyCycle,
    owner: str,
    productive: CalyxAutonomyCycle | None,
) -> dict[str, Any]:
    """Why the scheduler is not producing work, from recorded receipts only."""
    first = select(CalyxAutonomyCycle.finished_at).where(
        CalyxAutonomyCycle.owner == owner,
        CalyxAutonomyCycle.productive.is_(False),
    )
    if productive is not None:
        first = first.where(CalyxAutonomyCycle.finished_at > productive.finished_at)
    since = _aware(db.scalar(first.order_by(CalyxAutonomyCycle.finished_at).limit(1)))
    summary = json.loads(latest.replenishment_json) if latest.replenishment_json else {}
    detail = summary.get("detail") if isinstance(summary, dict) else None
    if not latest.replenishment_json:
        supply = "no_replenisher"
    elif isinstance(summary, dict) and summary.get("error"):
        supply = "replenisher_error"
    elif isinstance(detail, str) and detail.startswith("WORK_SOURCE_FAILED"):
        supply = "source_failed"
    elif isinstance(detail, str) and detail.split(":", 1)[0] in WORK_SUPPLY_PREFIXES:
        supply = WORK_SUPPLY_PREFIXES[detail.split(":", 1)[0]]
    else:
        supply = WORK_SUPPLY_STATES.get(str(detail), "unknown")
    return {
        "since": since.isoformat() if since else None,
        "category": latest.category,
        "reason_code": latest.reason_code,
        "upstream_zero_reason": summary.get("zero_reason")
        if isinstance(summary, dict)
        else None,
        "upstream_detail": detail,
        "work_supply": supply,
        "next_cycle_within_seconds": latest.poll_seconds,
    }


def _cycle_view(row: CalyxAutonomyCycle, now: datetime) -> dict[str, Any]:
    finished = _aware(row.finished_at)
    return {
        "cycle_id": row.cycle_id,
        "worker_id": row.worker_id,
        "sequence": row.sequence,
        "finished_at": finished.isoformat() if finished else None,
        "age_seconds": round((now - finished).total_seconds(), 1) if finished else None,
        "productive": row.productive,
        "category": row.category,
        "healthy": row.healthy,
        "reason_code": row.reason_code,
        "productive_jobs": row.productive_jobs,
        "job_keys": json.loads(row.job_keys_json or "[]"),
        "replenishment": json.loads(row.replenishment_json)
        if row.replenishment_json
        else None,
        "deployment_commit": row.deployment_commit,
    }


def autonomy_status(
    db: Session,
    *,
    owner: str,
    now: datetime | None = None,
    window: int = RECENT_WINDOW,
) -> dict[str, Any]:
    """Read-only scheduler/worker status from recorded cycles only."""
    moment = _aware(now) or datetime.now(UTC)
    rows = db.scalars(
        select(CalyxAutonomyCycle)
        .where(CalyxAutonomyCycle.owner == owner)
        .order_by(CalyxAutonomyCycle.finished_at.desc())
        .limit(window)
    ).all()
    if not rows:
        return {
            "state": "no_cycles_recorded",
            "heartbeat": None,
            "last_cycle": None,
            "last_productive": None,
            "last_defect": None,
            "consecutive_nonproductive": 0,
            "recent": {"window": 0, "productive": 0, "categories": {}},
        }
    latest = rows[0]
    last_cycle = _cycle_view(latest, moment)
    stale_after = 2 * max(latest.poll_seconds, 1) + HEARTBEAT_GRACE_SECONDS
    fresh = (
        last_cycle["age_seconds"] is not None
        and last_cycle["age_seconds"] <= stale_after
    )
    productive_row = next((row for row in rows if row.productive), None)
    if productive_row is None:
        productive_row = db.scalars(
            select(CalyxAutonomyCycle)
            .where(
                CalyxAutonomyCycle.owner == owner,
                CalyxAutonomyCycle.productive.is_(True),
            )
            .order_by(CalyxAutonomyCycle.finished_at.desc())
            .limit(1)
        ).first()
    defect_row = next(
        (row for row in rows if not row.productive and not row.healthy), None
    )
    consecutive = _consecutive_nonproductive(db, owner=owner, productive=productive_row)
    if not fresh:
        state = "stale"
    elif latest.productive:
        state = "productive"
    elif latest.healthy:
        state = "healthy_waiting"
    else:
        state = "defect"
    return {
        "state": state,
        "heartbeat": {
            "fresh": fresh,
            "age_seconds": last_cycle["age_seconds"],
            "stale_after_seconds": stale_after,
            "worker_id": latest.worker_id,
        },
        "last_cycle": last_cycle,
        "last_productive": _cycle_view(productive_row, moment)
        if productive_row
        else None,
        "last_defect": _cycle_view(defect_row, moment) if defect_row else None,
        "consecutive_nonproductive": consecutive,
        "idle": None
        if latest.productive
        else _idle_view(db, latest, owner, productive_row),
        "recent": {
            "window": len(rows),
            "productive": sum(1 for row in rows if row.productive),
            "categories": dict(
                sorted(Counter(row.category for row in rows if row.category).items())
            ),
        },
    }
