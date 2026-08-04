from __future__ import annotations

from typing import Any


def evaluate_preflight_execution_lock(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in ("lock_id", "holder", "acquired_at", "expires_at"):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")
    if payload.get("active") is not True:
        blockers.append("lock_not_active")
    if payload.get("concurrent_run_count") != 1:
        blockers.append("concurrent_preflight_execution")
    return {
        "exclusive_lock_confirmed": not blockers,
        "blockers": blockers,
        "release_required": True,
        "production_action_authorized": False,
    }
