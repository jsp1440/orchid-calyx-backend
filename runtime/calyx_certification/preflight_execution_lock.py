from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_preflight_execution_lock(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in ("lock_id", "holder", "acquired_at", "expires_at"):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")
    if payload.get("active") is not True:
        blockers.append("lock_not_active")

    count = payload.get("concurrent_run_count")
    if isinstance(count, bool) or not isinstance(count, int):
        blockers.append("invalid_concurrent_run_count")
    elif count == 0:
        blockers.append("no_preflight_lock_held")
    elif count > 1:
        blockers.append("concurrent_preflight_execution")

    expires_at = _parse_utc(payload.get("expires_at"))
    evaluated_at = _parse_utc(payload.get("evaluated_at")) or datetime.now(timezone.utc)
    if payload.get("expires_at") not in (None, "") and expires_at is None:
        blockers.append("invalid:expires_at")
    elif expires_at is not None and expires_at <= evaluated_at:
        blockers.append("preflight_lock_expired")

    return {
        "exclusive_lock_confirmed": not blockers,
        "blockers": blockers,
        "release_required": True,
        "production_action_authorized": False,
    }
