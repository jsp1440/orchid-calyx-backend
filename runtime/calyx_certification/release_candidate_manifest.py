from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def build_release_candidate_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    required = (
        "release_id",
        "commit_sha",
        "snapshot_hash",
        "dependency_manifest_hash",
        "rollback_hash",
    )
    blockers = [f"missing:{key}" for key in required if payload.get(key) in (None, "")]
    evidence_hashes = list(payload.get("evidence_hashes") or [])
    if not evidence_hashes:
        blockers.append("missing:evidence_hashes")
    if len(evidence_hashes) != len(set(evidence_hashes)):
        blockers.append("duplicate_evidence_hash")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "manifest_valid": not blockers,
        "blockers": blockers,
        "manifest_hash": sha256(canonical.encode()).hexdigest(),
        "manual_execution_required": True,
        "production_action_authorized": False,
    }
