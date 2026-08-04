from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def build_environment_fingerprint(payload: dict[str, Any]) -> dict[str, Any]:
    required = ("runtime", "region", "service", "database_host", "mount_path")
    blockers = [f"missing:{key}" for key in required if not payload.get(key)]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "fingerprint_ready": not blockers,
        "environment_hash": sha256(canonical.encode()).hexdigest(),
        "blockers": blockers,
        "production_action_authorized": False,
    }
