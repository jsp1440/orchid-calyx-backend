from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

_REQUIRED = {
    "run_id",
    "deployed_commit_sha",
    "route_reachable",
    "owner_authenticated",
    "database_connected",
    "persistent_mount_writable",
    "dry_run_directory_writable",
    "production_mutation_count",
    "captured_at",
}


def validate_live_preflight_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(key for key in _REQUIRED if payload.get(key) in (None, ""))
    blockers: list[str] = [f"missing:{key}" for key in missing]
    for key in (
        "route_reachable",
        "owner_authenticated",
        "database_connected",
        "persistent_mount_writable",
        "dry_run_directory_writable",
    ):
        if payload.get(key) is not True:
            blockers.append(f"failed:{key}")
    if payload.get("production_mutation_count") != 0:
        blockers.append("production_mutation_detected")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "evidence_accepted": not blockers,
        "blockers": sorted(set(blockers)),
        "artifact_hash": sha256(canonical.encode()).hexdigest(),
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
