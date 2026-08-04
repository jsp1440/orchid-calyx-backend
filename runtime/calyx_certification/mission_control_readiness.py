from __future__ import annotations

from typing import Any


def assemble_readiness_view(
    snapshot: dict[str, Any], live_evidence: dict[str, Any]
) -> dict[str, Any]:
    blockers = sorted(
        set(snapshot.get("blockers", [])) | set(live_evidence.get("blockers", []))
    )
    ready = (
        bool(snapshot.get("certified"))
        and bool(live_evidence.get("evidence_accepted"))
        and not blockers
    )
    return {
        "status": "ready" if ready else "blocked",
        "blockers": blockers,
        "snapshot_hash": snapshot.get("snapshot_hash"),
        "live_evidence_hash": live_evidence.get("artifact_hash"),
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
