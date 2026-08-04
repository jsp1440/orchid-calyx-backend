from __future__ import annotations

REQUIRED_STAGES = (
    "source_ingestion",
    "evidence_extraction",
    "concept_mapping",
    "graph_context",
    "inference",
    "reasoning_ledger",
    "conflict_uncertainty",
    "current_approval",
    "controlled_publication",
    "post_publication_monitoring",
)


def validate_acceptance_manifest(manifest: dict) -> dict:
    stages = manifest.get("stages") or {}
    blockers: list[str] = []
    for stage in REQUIRED_STAGES:
        payload = stages.get(stage)
        if not isinstance(payload, dict):
            blockers.append(f"{stage}:MISSING")
            continue
        if payload.get("passed") is not True:
            blockers.append(f"{stage}:NOT_PASSED")
        if not payload.get("artifact_id"):
            blockers.append(f"{stage}:ARTIFACT_ID_MISSING")
        if not payload.get("provenance"):
            blockers.append(f"{stage}:PROVENANCE_MISSING")

    invariants = manifest.get("invariants") or {}
    required_invariants = (
        "idempotent_duplicate_delivery",
        "cross_owner_denied",
        "stale_write_rejected",
        "approval_invalidated_after_mutation",
        "source_hash_mismatch_rejected",
        "private_reasoning_rejected",
    )
    for name in required_invariants:
        if invariants.get(name) is not True:
            blockers.append(f"invariant:{name}:FAILED")

    return {
        "certified": not blockers,
        "blockers": blockers,
        "required_stage_count": len(REQUIRED_STAGES),
        "production_action_authorized": False,
    }
