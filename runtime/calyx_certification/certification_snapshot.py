from __future__ import annotations

from hashlib import sha256
import json
from typing import Any


def build_certification_snapshot(bundle: dict[str, Any], status: dict[str, Any]) -> dict[str, Any]:
    blockers = sorted(set(bundle.get("blockers", [])) | set(status.get("blockers", [])))
    payload = {
        "bundle_hash": bundle.get("artifact_hash"),
        "status": status.get("status"),
        "blockers": blockers,
        "owner_authorization_required": True,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    payload["snapshot_hash"] = sha256(canonical.encode()).hexdigest()
    payload["certified"] = bool(bundle.get("certified")) and status.get("status") == "ready" and not blockers
    payload["production_action_authorized"] = False
    return payload
