from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def build_owner_handoff_package(payload: dict[str, Any]) -> dict[str, Any]:
    required = (
        "certification_report_hash",
        "release_candidate_hash",
        "blockers",
        "recommended_decision",
        "generated_at",
    )
    blockers = [f"missing:{key}" for key in required if payload.get(key) in (None, "")]
    if payload.get("recommended_decision") not in {"approve", "reject", "defer"}:
        blockers.append("invalid_recommended_decision")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "handoff_ready": not blockers,
        "handoff_hash": sha256(canonical.encode()).hexdigest(),
        "blockers": sorted(set(blockers)),
        "owner_decision_required": True,
        "production_action_authorized": False,
    }
