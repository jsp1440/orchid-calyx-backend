from datetime import datetime, timezone
from typing import Any


def evaluate_certification_expiry(record: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    expires_at = record.get("expires_at")
    blockers = []
    try:
        expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        blockers.append("invalid_expiry")
        expiry = now
    if expiry <= now:
        blockers.append("certification_expired")
    return {
        "current": not blockers,
        "blockers": sorted(set(blockers)),
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
