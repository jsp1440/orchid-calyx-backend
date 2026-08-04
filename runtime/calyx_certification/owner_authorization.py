from typing import Any


def validate_owner_authorization(record: dict[str, Any]) -> dict[str, Any]:
    required = ("owner_id", "decision", "snapshot_hash", "decided_at")
    blockers = [f"missing:{key}" for key in required if not record.get(key)]
    if record.get("decision") not in {"approve", "reject"}:
        blockers.append("invalid_decision")
    return {
        "valid": not blockers,
        "approved": not blockers and record.get("decision") == "approve",
        "blockers": blockers,
        "production_action_authorized": False,
    }
