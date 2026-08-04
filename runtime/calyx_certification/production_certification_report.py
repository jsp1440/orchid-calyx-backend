from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def build_production_certification_report(payload: dict[str, Any]) -> dict[str, Any]:
    required = (
        "report_id",
        "commit_sha",
        "snapshot_hash",
        "live_evidence_hash",
        "release_gate_hash",
        "owner_decision_id",
    )
    blockers = [f"missing:{key}" for key in required if payload.get(key) in (None, "")]
    required_checks = (
        "snapshot_certified",
        "live_evidence_accepted",
        "dependencies_complete",
        "rollback_ready",
        "evidence_retained",
        "owner_approved_current",
        "certification_current",
    )
    for key in required_checks:
        if payload.get(key) is not True:
            blockers.append(f"failed:{key}")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "production_certified": not blockers,
        "blockers": blockers,
        "report_hash": sha256(canonical.encode()).hexdigest(),
        "owner_authorization_required": True,
        "manual_release_required": True,
        "production_action_authorized": False,
    }
