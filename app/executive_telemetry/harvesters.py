from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.routers.mission_control import harvester_rows


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _status(raw: str | None, enabled: bool) -> str:
    value = str(raw or "").lower()
    if value in {"running"}:
        return "running"
    if value in {"complete", "completed", "success", "succeeded", "idle"}:
        return "complete" if enabled else "idle"
    if value in {"failed", "error"}:
        return "failed"
    if value in {"warning"}:
        return "warning"
    if value in {"planned"}:
        return "unavailable"
    if value in {"unknown", ""}:
        return "unavailable"
    return value


def normalize_harvester(row: dict[str, Any], *, include_operations: bool = False) -> dict[str, Any]:
    enabled = bool(row.get("enabled"))
    processed = int(row.get("rows_processed") or 0)
    inserted = int(row.get("rows_inserted") or 0)
    target = row.get("target_records")
    target_int = int(target) if isinstance(target, (int, float)) else None
    completion = round((processed / target_int) * 100, 2) if target_int and target_int > 0 else None
    duplicates = int(row.get("duplicates") or max(processed - inserted, 0))
    duplicate_rate = round((duplicates / processed) * 100, 2) if processed > 0 else 0.0
    errors = [str(item) for item in (row.get("errors") or []) if item]
    status = _status(row.get("state"), enabled)
    unavailable = status == "unavailable"

    payload: dict[str, Any] = {
        "source_id": row.get("id"),
        "title": row.get("name"),
        "category_badges": ["Harvester", "Telemetry"],
        "source": row.get("source"),
        "version": row.get("version") or "unavailable",
        "status": status,
        "narrative_summary": row.get("logSummary") or "No telemetry summary was supplied.",
        "next_action": "Restore the telemetry source and verify the latest job heartbeat." if unavailable else "Review the latest run and continue the authorized workflow.",
        "metric": processed,
        "records_processed": processed,
        "records_inserted": inserted,
        "target_records": target_int,
        "completion_percentage": completion,
        "duplicate_count": duplicates,
        "duplicate_rate": duplicate_rate,
        "failures": errors,
        "warnings": int(row.get("warning_count") or 0),
        "throughput": row.get("throughput"),
        "queue_remaining": row.get("queue_remaining"),
        "last_successful_activity": row.get("last_run"),
        "freshness": row.get("heartbeat_at") or "unavailable",
        "schedule": row.get("schedule") or "unavailable",
        "estimated_completion": row.get("estimated_completion"),
        "approval_state": "owner_authorization_required",
        "calyx_context": {
            "recommendation_signal": "unavailable" if unavailable else "observe",
            "reason": errors[0] if errors else "Telemetry is derived from the latest governed execution heartbeat.",
            "confidence": 0.2 if unavailable else 0.7,
        },
        "provenance": {
            "evidence_source": "oc_admin.ocp_execution_jobs",
            "checkpoint": row.get("checkpoint"),
            "generated_at": _now(),
        },
    }
    if include_operations:
        payload["allowed_actions"] = {
            "run_now": row.get("runNow") == "allowed",
            "pause_resume": row.get("pauseResume") == "allowed",
        }
    else:
        payload["allowed_actions"] = {}
    return payload


def normalized_harvesters(*, include_operations: bool = False) -> list[dict[str, Any]]:
    return [normalize_harvester(row, include_operations=include_operations) for row in harvester_rows()]
