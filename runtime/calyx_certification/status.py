from __future__ import annotations


def build_certification_status(*, graph: dict, brain: dict, autonomy: dict, monitoring: dict) -> dict:
    blockers: list[dict[str, str]] = []

    if graph.get("ready") is not True:
        blockers.append({"lane": "knowledge_graph", "code": "GRAPH_NOT_READY"})
    if brain.get("full_chain_certified") is not True:
        blockers.append({"lane": "brain", "code": "BRAIN_NOT_CERTIFIED"})
    if autonomy.get("worker_enabled") is not True:
        blockers.append({"lane": "autonomy", "code": "WORKER_NOT_ENABLED"})
    if autonomy.get("dead_letter_count", 0) > 0:
        blockers.append({"lane": "autonomy", "code": "DEAD_LETTER_PRESENT"})
    if autonomy.get("stale_approval_count", 0) > 0:
        blockers.append({"lane": "governance", "code": "STALE_APPROVAL_PRESENT"})
    if monitoring.get("operational") is not True:
        blockers.append({"lane": "monitoring", "code": "MONITORING_NOT_OPERATIONAL"})

    unavailable = []
    for lane, payload in (
        ("knowledge_graph", graph),
        ("brain", brain),
        ("autonomy", autonomy),
        ("monitoring", monitoring),
    ):
        if payload.get("available") is False:
            unavailable.append({"lane": lane, "reason": payload.get("reason") or "unavailable"})

    return {
        "certification_ready": not blockers and not unavailable,
        "blockers": blockers,
        "unavailable_dependencies": unavailable,
        "metrics": {
            "queue_depth": autonomy.get("queue_depth", 0),
            "oldest_pending_seconds": autonomy.get("oldest_pending_seconds"),
            "retry_count": autonomy.get("retry_count", 0),
            "dead_letter_count": autonomy.get("dead_letter_count", 0),
            "stale_approval_count": autonomy.get("stale_approval_count", 0),
            "monitoring_lag_seconds": monitoring.get("lag_seconds"),
        },
        "owner_authorization_required": True,
    }
