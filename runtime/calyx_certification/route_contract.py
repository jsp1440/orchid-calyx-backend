from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def build_route_contract_snapshot(routes: list[dict[str, Any]]) -> dict[str, Any]:
    blockers = [] if routes else ["no_routes"]
    for index, route in enumerate(routes):
        for key in ("method", "path", "auth_required", "response_schema"):
            if route.get(key) in (None, ""):
                blockers.append(f"route_{index}_missing:{key}")
    canonical = json.dumps(routes, sort_keys=True, separators=(",", ":"), default=str)
    return {
        "route_contract_ready": not blockers,
        "route_contract_hash": sha256(canonical.encode()).hexdigest(),
        "blockers": sorted(set(blockers)),
        "production_action_authorized": False,
    }
