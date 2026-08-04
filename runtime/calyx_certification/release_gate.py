from __future__ import annotations

from typing import Any


def evaluate_release_gate(inputs: dict[str, Any]) -> dict[str, Any]:
    required_true = (
        "snapshot_certified",
        "live_evidence_accepted",
        "owner_approved",
        "dependencies_complete",
        "rollback_ready",
        "evidence_retained",
        "certification_current",
    )
    blockers = [
        f"failed:{key}" for key in required_true if inputs.get(key) is not True
    ]
    return {
        "release_eligible": not blockers,
        "blockers": blockers,
        "manual_execution_required": True,
        "production_action_authorized": False,
    }
