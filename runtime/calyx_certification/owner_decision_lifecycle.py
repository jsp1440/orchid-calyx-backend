from __future__ import annotations

from typing import Any

_ALLOWED_DECISIONS = {"approved", "rejected", "revoked"}


def _strict_flag(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key, False)
    return value is True or (isinstance(value, int) and not isinstance(value, bool) and value == 1)


def evaluate_owner_decision_lifecycle(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in ("decision_id", "snapshot_hash", "owner_id", "decided_at"):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")
    decision = payload.get("decision")
    if decision not in _ALLOWED_DECISIONS:
        blockers.append("invalid_owner_decision")
    if _strict_flag(payload, "expired"):
        blockers.append("owner_decision_expired")
    if _strict_flag(payload, "revoked") or decision == "revoked":
        blockers.append("owner_decision_revoked")
    approved_current = decision == "approved" and not blockers
    return {
        "approved_current": approved_current,
        "blockers": blockers,
        "owner_decision_recorded": decision in _ALLOWED_DECISIONS,
        "production_action_authorized": False,
    }
