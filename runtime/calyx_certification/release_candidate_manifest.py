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
    raw_hashes = payload.get("evidence_hashes")
    evidence_hashes = list(raw_hashes) if isinstance(raw_hashes, list) else []
    if not evidence_hashes:
        blockers.append("missing:evidence_hashes")
    if any(not isinstance(item, str) or not item.strip() for item in evidence_hashes):
        blockers.append("invalid_evidence_hash")
    if len(evidence_hashes) != len(set(evidence_hashes)):
        blockers.append("duplicate_evidence_hash")

    canonical_payload = {**payload, "evidence_hashes": sorted(evidence_hashes)}
    manifest = {
        "manifest_valid": not blockers,
        "blockers": sorted(blockers),
        "manual_execution_required": True,
        "production_action_authorized": False,
        "payload": canonical_payload,
    }
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return {**manifest, "manifest_hash": sha256(canonical.encode()).hexdigest()}
