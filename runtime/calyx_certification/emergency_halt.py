from __future__ import annotations

from typing import Any


def evaluate_emergency_halt(payload: dict[str, Any]) -> dict[str, Any]:
    raw_signals = payload.get("signals")
    signals = (
        [str(item).strip() for item in raw_signals if str(item).strip()]
        if isinstance(raw_signals, list)
        else []
    )
    halt_requested = payload.get("halt_requested") is True
    halt_required = halt_requested or bool(signals)
    blockers: list[str] = []

    if halt_required and not str(payload.get("reason") or "").strip():
        blockers.append("missing:halt_reason")
    if halt_required and payload.get("owner_notified") is not True:
        blockers.append("owner_notification_missing")
    if halt_required and payload.get("automated_release_disabled") is not True:
        blockers.append("automated_release_not_disabled")

    return {
        "halt_required": halt_required,
        "halt_record_valid": halt_required and not blockers,
        "signals": sorted(set(signals)),
        "blockers": blockers,
        "manual_recovery_required": halt_required,
        "production_action_authorized": False,
    }
