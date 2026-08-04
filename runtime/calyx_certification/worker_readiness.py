from typing import Any


def validate_worker_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("worker_name", "heartbeat_at", "queue_connected", "dry_run_mode")
    blockers = [f"missing:{key}" for key in required if payload.get(key) in (None, "")]
    if payload.get("queue_connected") is not True:
        blockers.append("worker_queue_disconnected")
    if payload.get("dry_run_mode") is not True:
        blockers.append("worker_not_in_dry_run")
    return {
        "worker_ready": not blockers,
        "blockers": sorted(set(blockers)),
        "production_action_authorized": False,
    }
