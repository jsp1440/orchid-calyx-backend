from __future__ import annotations

from typing import Any


def assemble_readiness_view(
    snapshot: dict[str, Any],
    live_evidence: dict[str, Any],
    *,
    licensed_image_pipeline: dict[str, Any] | None = None,
    literature_pipeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble the Mission Control readiness view.

    Parameters
    ----------
    snapshot:
        Certification snapshot report (``certified``, ``blockers``, …).
    live_evidence:
        Live preflight evidence report (``evidence_accepted``, ``blockers``, …).
    licensed_image_pipeline:
        Optional readiness report for the licensed-image pipeline.  Expected
        keys: ``ready`` (bool), ``blockers`` (list[str]).
    literature_pipeline:
        Optional readiness report for the literature acquisition pipeline.
        Expected keys: ``ready`` (bool), ``blockers`` (list[str]).
    """
    pipeline_blockers: list[str] = []

    image_status: dict[str, Any] = {"ready": None, "blockers": []}
    if licensed_image_pipeline is not None:
        img_ready = bool(licensed_image_pipeline.get("ready"))
        img_blockers = list(licensed_image_pipeline.get("blockers") or [])
        image_status = {"ready": img_ready, "blockers": img_blockers}
        if not img_ready:
            pipeline_blockers.extend(img_blockers)

    lit_status: dict[str, Any] = {"ready": None, "blockers": []}
    if literature_pipeline is not None:
        lit_ready = bool(literature_pipeline.get("ready"))
        lit_blockers = list(literature_pipeline.get("blockers") or [])
        lit_status = {"ready": lit_ready, "blockers": lit_blockers}
        if not lit_ready:
            pipeline_blockers.extend(lit_blockers)

    blockers = sorted(
        set(snapshot.get("blockers", []))
        | set(live_evidence.get("blockers", []))
        | set(pipeline_blockers)
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
        "pipelines": {
            "licensed_image": image_status,
            "literature": lit_status,
        },
    }
