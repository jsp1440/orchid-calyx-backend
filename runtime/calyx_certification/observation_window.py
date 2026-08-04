from __future__ import annotations

from datetime import datetime
from typing import Any


def validate_observation_window(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    try:
        started = datetime.fromisoformat(str(payload.get("started_at")).replace("Z", "+00:00"))
        ended = datetime.fromisoformat(str(payload.get("ended_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        blockers.append("invalid_observation_timestamp")
        started = ended = datetime.min
    minimum_seconds = payload.get("minimum_seconds")
    if not isinstance(minimum_seconds, int) or minimum_seconds < 0:
        blockers.append("invalid_minimum_seconds")
    elif (ended - started).total_seconds() < minimum_seconds:
        blockers.append("observation_window_too_short")
    if payload.get("health_stable") is not True:
        blockers.append("health_not_stable")
    return {
        "observation_complete": not blockers,
        "blockers": sorted(set(blockers)),
        "production_action_authorized": False,
    }
