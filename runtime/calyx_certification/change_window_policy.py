from __future__ import annotations

from datetime import datetime
from typing import Any


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
    if start and end and start >= end:
        blockers.append("invalid_change_window_order")
    if start and end and now and not (start <= now <= end):
        blockers.append("outside_approved_change_window")
    if payload.get("owner_window_approved") is not True:
        blockers.append("owner_window_approval_missing")
    return {
        "within_approved_window": not blockers,
        "blockers": blockers,
        "manual_execution_required": True,
        "production_action_authorized": False,
    }
