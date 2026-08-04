from __future__ import annotations

from typing import Any


def validate_policy_version(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("policy_name", "policy_version", "approved_version", "effective_at")
    blockers = [f"missing:{key}" for key in required if not payload.get(key)]
    if payload.get("policy_version") != payload.get("approved_version"):
        blockers.append("policy_version_mismatch")
    return {
        "policy_current": not blockers,
        "blockers": sorted(set(blockers)),
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
