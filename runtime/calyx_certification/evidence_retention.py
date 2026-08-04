from __future__ import annotations

from typing import Any


def validate_evidence_retention(record: dict[str, Any]) -> dict[str, Any]:
    required = ("artifact_hash", "storage_uri", "retention_until", "immutable")
    blockers = [
        f"missing:{key}" for key in required if record.get(key) in (None, "")
    ]
    if record.get("immutable") is not True:
        blockers.append("evidence_not_immutable")
    return {
        "retained": not blockers,
        "blockers": blockers,
        "production_action_authorized": False,
    }
