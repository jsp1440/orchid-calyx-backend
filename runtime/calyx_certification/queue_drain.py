from typing import Any


def validate_queue_drain(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("queue_name", "pending_jobs", "active_jobs", "dead_letter_jobs")
    blockers = [f"missing:{key}" for key in required if payload.get(key) is None]
    for key in ("pending_jobs", "active_jobs", "dead_letter_jobs"):
        value = payload.get(key)
        if isinstance(value, int) and value != 0:
            blockers.append(f"queue_not_drained:{key}")
    return {
        "queue_drained": not blockers,
        "blockers": sorted(set(blockers)),
        "production_action_authorized": False,
    }
