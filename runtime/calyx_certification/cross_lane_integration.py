REQUIRED_LANES = (
    "deployed_preflight",
    "all_domain_graph",
    "source_binding",
    "reasoning_ledger",
    "controlled_publication",
    "publication_monitoring",
    "concept_registry_consumers",
    "literature_ingestion",
    "full_chain_manifest",
    "mission_control_status",
)


def validate_cross_lane_integration(evidence: dict) -> dict:
    lanes = evidence.get("lanes") or {}
    blockers = []
    artifact_hashes = set()
    for lane in REQUIRED_LANES:
        result = lanes.get(lane)
        if not isinstance(result, dict):
            blockers.append(f"{lane}:MISSING")
            continue
        if result.get("certified") is not True:
            blockers.append(f"{lane}:NOT_CERTIFIED")
        artifact_hash = result.get("artifact_hash")
        if not artifact_hash:
            blockers.append(f"{lane}:ARTIFACT_HASH_MISSING")
        else:
            artifact_hashes.add(artifact_hash)
    if len(artifact_hashes) != len(REQUIRED_LANES):
        blockers.append("ARTIFACT_HASH_CARDINALITY_MISMATCH")
    return {
        "integrated": not blockers,
        "blockers": blockers,
        "lane_count": len(REQUIRED_LANES),
        "owner_authorization_required": True,
        "production_action_authorized": False,
    }
