from __future__ import annotations

from typing import Any


def evaluate_evidence_signature(payload: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    for key in ("artifact_hash", "signature", "public_key_id", "algorithm"):
        if payload.get(key) in (None, ""):
            blockers.append(f"missing:{key}")
    if payload.get("algorithm") not in {"ed25519", "rsa-pss-sha256"}:
        blockers.append("unsupported_signature_algorithm")
    if payload.get("signature_verified") is not True:
        blockers.append("signature_not_verified")
    if payload.get("artifact_hash_matches") is not True:
        blockers.append("artifact_hash_mismatch")
    return {
        "signature_accepted": not blockers,
        "blockers": blockers,
        "verification_required": True,
        "production_action_authorized": False,
    }
