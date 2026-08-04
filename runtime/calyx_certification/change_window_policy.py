from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_change_window(payload: dict[str, Any]) -> dict[str, Any]:
    start = _parse(payload.get("window_start"))
    end = _parse(payload.get("window_end"))
    now = _parse(payload.get("evaluated_at"))
    blockers: list[str] = []
    if start is None:
        blockers.append("invalid:window_start")
    if end is None:
        blockers.append("invalid:window_end")
    if now is None:
        blockers.append("invalid:evaluated_at")

    ordered = bool(start and end and start < end)
    if start and end and not ordered:
        blockers.append("invalid_change_window_order")
    if ordered and now and not (start <= now <= end):
        blockers.append("outside_approved_change_window")
    if payload.get("owner_window_approved") is not True:
        blockers.append("owner_window_approval_missing")
    return {
        "within_approved_window": not blockers,
        "blockers": blockers,
        "manual_execution_required": True,
        "production_action_authorized": False,
    }
