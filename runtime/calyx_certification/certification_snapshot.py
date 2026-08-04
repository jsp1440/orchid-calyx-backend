from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def _canonical_blockers(*groups: Any) -> list[Any]:
    by_canonical: dict[str, Any] = {}
    for group in groups:
        for blocker in group or []:
            canonical = json.dumps(blocker, sort_keys=True, separators=(",", ":"), default=str)
            by_canonical[canonical] = blocker
    return [by_canonical[key] for key in sorted(by_canonical)]


def build_certification_snapshot(
    bundle: dict[str, Any], status: dict[str, Any]
) -> dict[str, Any]:
    blockers = _canonical_blockers(bundle.get("blockers"), status.get("blockers"))
    bundle_complete = bundle.get("complete") is True or bundle.get("certified") is True
    status_ready = status.get("status") == "ready" or status.get("certification_ready") is True
    certified = bundle_complete and status_ready and not blockers

    payload = {
        "bundle_hash": bundle.get("artifact_hash"),
        "status": status.get("status"),
        "certification_ready": status.get("certification_ready"),
        "blockers": blockers,
        "owner_authorization_required": True,
        "certified": certified,
        "production_action_authorized": False,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {**payload, "snapshot_hash": sha256(canonical.encode()).hexdigest()}
