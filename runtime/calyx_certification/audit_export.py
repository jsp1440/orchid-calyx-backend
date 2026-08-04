from hashlib import sha256
import json
from typing import Any


def build_audit_export(records: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [] if records else ["no_records"]
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "export_ready": not blockers,
        "record_count": len(records),
        "export_hash": sha256(canonical.encode()).hexdigest(),
        "blockers": blockers,
        "production_action_authorized": False,
    }
