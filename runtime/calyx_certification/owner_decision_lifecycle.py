from __future__ import annotations

from typing import Any

_ALLOWED_DECISIONS = {"approved", "rejected", "revoked"}


def evaluate_owner_decision_lifecycle(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in ("decision_id", "snapshot_hash", "owner_id", "decided_at"):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")
    decision = payload.get("decision")
    if decision not in _ALLOWED_DECISIONS:
        blockers.append("invalid_owner_decision")
    if bool(payload.get("expired")):
        blockers.append("owner_decision_expired")
    if bool(payload.get("revoked")) or decision == "revoked":
        blockers.append("owner_decision_revoked")
    approved_current = decision == "approved" and not blockers
    return {
        "approved_current": approved_current,
        "blockers": blockers,
        "owner_decision_recorded": decision in _ALLOWED_DECISIONS,
        "production_action_authorized": False,
    }
