REQUIRED_CONSUMERS = {
    "literature_intelligence",
    "knowledge_graph",
    "calyx_grounding",
    "research_station",
    "species_dossiers",
}


def certify_concept_consumers(report: dict) -> dict:
    consumers = report.get("consumers") or {}
    blockers: list[str] = []
    canonical_registry_id = report.get("canonical_registry_id")
    canonical_version = report.get("canonical_version")
    if not canonical_registry_id:
        blockers.append("CANONICAL_REGISTRY_ID_MISSING")
    if not canonical_version:
        blockers.append("CANONICAL_VERSION_MISSING")

    for name in sorted(REQUIRED_CONSUMERS):
        payload = consumers.get(name)
        if not isinstance(payload, dict):
            blockers.append(f"{name}:MISSING")
            continue
        if payload.get("registry_id") != canonical_registry_id:
            blockers.append(f"{name}:REGISTRY_MISMATCH")
        if payload.get("registry_version") != canonical_version:
            blockers.append(f"{name}:VERSION_MISMATCH")
        if payload.get("owner_isolation") is not True:
            blockers.append(f"{name}:OWNER_ISOLATION_NOT_PROVEN")
        if payload.get("project_isolation") is not True:
            blockers.append(f"{name}:PROJECT_ISOLATION_NOT_PROVEN")
        if payload.get("deterministic_resolution") is not True:
            blockers.append(f"{name}:NONDETERMINISTIC_RESOLUTION")

    return {
        "certified": not blockers,
        "blockers": blockers,
        "consumer_count": len(REQUIRED_CONSUMERS),
        "publication_authorized": False,
    }
