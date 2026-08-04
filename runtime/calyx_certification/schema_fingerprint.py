from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def build_schema_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("migration_head", "table_count", "extension_versions")
    blockers = [f"missing:{key}" for key in required if payload.get(key) in (None, "")]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "schema_fingerprint_ready": not blockers,
        "schema_hash": sha256(canonical.encode()).hexdigest(),
        "blockers": blockers,
        "production_action_authorized": False,
    }
