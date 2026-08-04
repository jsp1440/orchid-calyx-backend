from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

_REQUIRED_IDENTITIES = {
    "run_id",
    "deployed_commit_sha",
    "captured_at",
}
_REQUIRED_FLAGS = (
    "route_reachable",
    "owner_authenticated",
    "database_connected",
    "persistent_mount_writable",
    "dry_run_directory_writable",
)


def validate_live_preflight_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in sorted(_REQUIRED_IDENTITIES):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")

    for key in _REQUIRED_FLAGS:
        if key not in payload or payload.get(key) is None:
            blockers.append(f"missing:{key}")
        elif payload.get(key) is not True:
            blockers.append(f"failed:{key}")

    mutation_count = payload.get("production_mutation_count")
    if mutation_count is None or mutation_count == "":
        blockers.append("missing:production_mutation_count")
    elif isinstance(mutation_count, bool) or not isinstance(mutation_count, int):
        blockers.append("invalid:production_mutation_count")
    elif mutation_count != 0:
        blockers.append("production_mutation_detected")

    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "evidence_accepted": not blockers,
        "blockers": sorted(set(blockers)),
        "artifact_hash": sha256(canonical.encode()).hexdigest(),
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
