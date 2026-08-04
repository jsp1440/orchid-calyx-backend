from __future__ import annotations

from typing import Any


def evaluate_emergency_halt(payload: dict[str, Any]) -> dict[str, Any]:
    signals = [str(item) for item in payload.get("signals", []) if str(item)]
    halt_requested = payload.get("halt_requested") is True
    blockers: list[str] = []
    if halt_requested and not payload.get("reason"):
        blockers.append("missing:halt_reason")
    if halt_requested and payload.get("owner_notified") is not True:
        blockers.append("owner_notification_missing")
    if halt_requested and payload.get("automated_release_disabled") is not True:
        blockers.append("automated_release_not_disabled")
    halt_required = halt_requested or bool(signals)
    return {
        "halt_required": halt_required,
        "halt_record_valid": halt_required and not blockers,
        "signals": sorted(set(signals)),
        "blockers": blockers,
        "manual_recovery_required": halt_required,
        "production_action_authorized": False,
    }
