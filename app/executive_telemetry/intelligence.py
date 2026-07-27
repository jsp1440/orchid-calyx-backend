from __future__ import annotations

from typing import Any


def build_dependency_intelligence(
    subsystems: list[dict[str, Any]],
    harvesters: list[dict[str, Any]],
) -> dict[str, Any]:
    subsystem_by_id = {str(item.get("id")): item for item in subsystems}
    harvester_by_id = {str(item.get("source_id")): item for item in harvesters}

    dependencies: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []

    def add_dependency(
        *,
        dependency_id: str,
        upstream: str,
        downstream: list[str],
        condition: bool,
        reason: str,
        impact: str,
        action: str,
        confidence: float,
    ) -> None:
        if not condition:
            return
        dependencies.append(
            {
                "id": dependency_id,
                "upstream": upstream,
                "downstream": downstream,
                "status": "attention_required",
                "reason": reason,
                "scientific_impact": impact,
                "recommended_action": action,
                "confidence": confidence,
            }
        )

    taxonomy = harvester_by_id.get("world_plants_hassler", {})
    traitbank = harvester_by_id.get("eol_traitbank", {})
    gbif = harvester_by_id.get("gbif", {})
    inaturalist = harvester_by_id.get("inaturalist", {})
    globi = harvester_by_id.get("globi", {})
    pollinators = harvester_by_id.get("pollinator_datasets", {})

    add_dependency(
        dependency_id="taxonomy-knowledge-graph-reindex",
        upstream="world_plants_hassler",
        downstream=["species_explorer", "knowledge_graph", "literature", "atlas"],
        condition=taxonomy.get("status") in {"running", "warning", "failed", "unavailable"},
        reason="The taxonomic backbone is not in a stable complete state.",
        impact="Name changes or unresolved taxonomy can invalidate graph bindings, literature links, and occurrence displays.",
        action="Complete or restore World Plants telemetry, then queue a governed taxonomy reindex.",
        confidence=0.9,
    )

    trait_completion = traitbank.get("completion_percentage")
    add_dependency(
        dependency_id="trait-coverage-culture-sheets",
        upstream="eol_traitbank",
        downstream=["knowledge_graph", "culture_sheets"],
        condition=traitbank.get("status") in {"warning", "failed", "unavailable"}
        or (isinstance(trait_completion, (int, float)) and trait_completion < 75),
        reason="Trait coverage is insufficient or unavailable.",
        impact="Culture-sheet generation and trait-based inference may be incomplete or low confidence.",
        action="Prioritize TraitBank ingestion and ontology mapping before expanding automated culture sheets.",
        confidence=0.88,
    )

    occurrence_attention = any(
        item.get("status") in {"warning", "failed", "unavailable"}
        for item in (gbif, inaturalist)
    )
    add_dependency(
        dependency_id="occurrence-freshness-atlas",
        upstream="gbif_and_inaturalist",
        downstream=["atlas", "conservation"],
        condition=occurrence_attention,
        reason="One or more primary occurrence sources are stale, unavailable, or degraded.",
        impact="Distribution maps, conservation summaries, and geographic completeness may be misleading.",
        action="Restore occurrence-source telemetry and refresh Atlas distributions after validation.",
        confidence=0.92,
    )

    pollinator_attention = any(
        item.get("status") in {"warning", "failed", "unavailable"}
        for item in (globi, pollinators)
    )
    add_dependency(
        dependency_id="pollinator-coverage-ecological-completeness",
        upstream="globi_and_pollinator_datasets",
        downstream=["pollinators", "knowledge_graph", "completeness"],
        condition=pollinator_attention,
        reason="Interaction telemetry is missing or degraded for one or more pollinator sources.",
        impact="Ecological completeness and pollination relationship coverage remain understated.",
        action="Restore interaction adapters and prioritize taxa with no verified pollinator evidence.",
        confidence=0.9,
    )

    blocked_subsystems = [
        item for item in subsystems if str(item.get("status")) in {"blocked", "warning", "planned"}
    ]
    if dependencies:
        highest = dependencies[0]
        recommendations.append(
            {
                "id": "calyx-primary-recommendation",
                "status": "attention_required",
                "recommendation": highest["recommended_action"],
                "reason": highest["reason"],
                "confidence": highest["confidence"],
                "expected_scientific_gain": highest["scientific_impact"],
                "dependency_impact": highest["downstream"],
                "next_authorized_action": highest["recommended_action"],
            }
        )
    elif blocked_subsystems:
        first = blocked_subsystems[0]
        recommendations.append(
            {
                "id": "calyx-primary-recommendation",
                "status": "observe",
                "recommendation": first.get("recommended_action") or "Review the highest-priority degraded subsystem.",
                "reason": first.get("summary") or "A subsystem requires operational review.",
                "confidence": float(first.get("confidence") or 0.6),
                "expected_scientific_gain": "Improved operational reliability and evidence completeness.",
                "dependency_impact": first.get("dependencies") or [],
                "next_authorized_action": first.get("recommended_action") or "Review subsystem telemetry.",
            }
        )
    else:
        recommendations.append(
            {
                "id": "calyx-primary-recommendation",
                "status": "stable",
                "recommendation": "Continue observation and preserve current governed operating posture.",
                "reason": "No cross-module dependency currently requires intervention.",
                "confidence": 0.85,
                "expected_scientific_gain": "Maintains reliable telemetry and avoids unnecessary intervention.",
                "dependency_impact": [],
                "next_authorized_action": "No action required.",
            }
        )

    return {
        "recommendations": recommendations,
        "dependencies": dependencies,
        "summary": {
            "dependency_count": len(dependencies),
            "attention_required": bool(dependencies),
        },
        "governance": {
            "read_only": True,
            "does_not_publish": True,
            "does_not_grant_scientific_authority": True,
        },
    }
