"""BUILD-062 deterministic intelligence derivation for Mission Control.

Replaces static recommendations with backend-generated recommendations derived
from live adapter payloads.  All derivation is pure-function (no side effects,
no DB access) so it can be tested in isolation.

Phase 3 intelligence items:
- Highest scientific priority
- Largest knowledge gap
- Most active subsystem
- Recently completed work
- Data collection bottlenecks
- Suggested next action
- Recommended owner
- Grant opportunities
- Publication opportunities
- Research risks
"""

from __future__ import annotations

from typing import Any

from runtime.scientific_intelligence.utils import to_int, to_float


# ---------------------------------------------------------------------------
# Phase 3 — Individual derivation functions
# ---------------------------------------------------------------------------


def highest_scientific_priority(adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return the subsystem with the most urgent scientific need."""
    # Priority order: KG gaps > pollinator coverage < mycorrhiza coverage < literature < atlas
    scores: list[tuple[str, float, str]] = []

    kg = adapters.get("knowledge_graph", {})
    if kg.get("available"):
        entities = to_int(kg.get("entities"))
        relationships = to_int(kg.get("relationships"))
        gap = max(0, entities - relationships) if entities > 0 else 10000
        scores.append(("knowledge_graph", gap / max(entities, 1) if entities > 0 else 1.0, "Knowledge Graph relationship gap"))

    pollinators = adapters.get("pollinators", {})
    if pollinators.get("available"):
        coverage = to_float(pollinators.get("coverage_pct"))
        scores.append(("pollinators", (100 - coverage) / 100, "Pollinator coverage gap"))

    mycorrhiza = adapters.get("mycorrhiza", {})
    if mycorrhiza.get("available"):
        coverage = to_float(mycorrhiza.get("coverage_pct"))
        scores.append(("mycorrhiza", (100 - coverage) / 100, "Mycorrhizal coverage gap"))

    lit = adapters.get("literature", {})
    if lit.get("available"):
        docs = to_int(lit.get("documents"))
        extracted = to_int(lit.get("extracted_relationships"))
        ratio = 1 - (extracted / max(docs * 5, 1)) if docs > 0 else 1.0
        scores.append(("literature", max(0.0, ratio), "Literature extraction gap"))

    if not scores:
        return {"subsystem_id": "knowledge_graph", "reason": "No live data available; Knowledge Graph is the recommended priority by default.", "score": 1.0}

    subsystem_id, score, reason = max(scores, key=lambda x: x[1])
    return {"subsystem_id": subsystem_id, "reason": reason, "score": round(score, 4)}


def largest_knowledge_gap(adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Identify the subsystem with the most significant data gap."""
    kg = adapters.get("knowledge_graph", {})
    atlas = adapters.get("atlas", {})
    lit = adapters.get("literature", {})

    gaps: list[tuple[str, int, str]] = []

    if kg.get("available"):
        entities = to_int(kg.get("entities"))
        relationships = to_int(kg.get("relationships"))
        gaps.append(("knowledge_graph", max(0, entities - relationships), "Missing entity-to-relationship links"))

    if atlas.get("available"):
        occurrences = to_int(atlas.get("occurrences"))
        taxa = to_int(atlas.get("taxa_covered"))
        gaps.append(("atlas", max(0, taxa * 10 - occurrences), "Occurrence records below target density"))

    if lit.get("available"):
        documents = to_int(lit.get("documents"))
        extracted = to_int(lit.get("extracted_relationships"))
        gaps.append(("literature", max(0, documents * 5 - extracted), "Unextracted literature relationships"))

    if not gaps:
        return {"subsystem_id": "knowledge_graph", "gap_size": 0, "description": "No live data available to measure gaps."}

    subsystem_id, gap_size, description = max(gaps, key=lambda x: x[1])
    return {"subsystem_id": subsystem_id, "gap_size": gap_size, "description": description}


def most_active_subsystem(adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Return the subsystem with the most recently-touched data."""
    activity: list[tuple[str, int]] = []
    for key, payload in adapters.items():
        if not payload.get("available"):
            continue
        count = max(
            to_int(payload.get("entities")),
            to_int(payload.get("relationships")),
            to_int(payload.get("occurrences")),
            to_int(payload.get("documents")),
            to_int(payload.get("records")),
            to_int(payload.get("images")),
        )
        activity.append((key, count))

    if not activity:
        return {"subsystem_id": "harvesters", "metric": 0, "reason": "No live subsystems detected."}

    subsystem_id, metric = max(activity, key=lambda x: x[1])
    return {"subsystem_id": subsystem_id, "metric": metric, "reason": f"{subsystem_id} has the highest record volume ({metric:,})"}


def recently_completed_work(adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """List subsystems that have live data, indicating recent harvest/ingestion."""
    completed = []
    labels = {
        "knowledge_graph": "Knowledge Graph entities and relationships indexed",
        "atlas": "Atlas occurrence records loaded",
        "literature": "Literature documents ingested",
        "pollinators": "Pollinator relationship records harvested",
        "mycorrhiza": "Mycorrhizal records harvested",
        "vision": "Image records indexed",
        "grant_office": "Grant intelligence derived",
    }
    for key, payload in adapters.items():
        if payload.get("available") and payload.get("status") == "live":
            completed.append({"subsystem_id": key, "summary": labels.get(key, f"{key} data available")})
    return completed


def data_collection_bottlenecks(adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify subsystems with no data or low coverage."""
    bottlenecks = []
    for key, payload in adapters.items():
        if not payload.get("available"):
            bottlenecks.append({
                "subsystem_id": key,
                "severity": "high",
                "reason": f"{payload.get('name', key)} adapter is unavailable — database table missing or unreachable.",
            })
            continue
        if payload.get("status") == "empty":
            bottlenecks.append({
                "subsystem_id": key,
                "severity": "medium",
                "reason": f"{payload.get('name', key)} source table is reachable but contains no records.",
            })
            continue
        coverage = to_float(payload.get("coverage_pct") or payload.get("coordinate_coverage_pct"))
        if 0 < coverage < 10:
            bottlenecks.append({
                "subsystem_id": key,
                "severity": "medium",
                "reason": f"{payload.get('name', key)} coverage is critically low ({coverage:.1f}%).",
            })
    return bottlenecks


def suggested_next_action(
    adapters: dict[str, dict[str, Any]],
    bottlenecks: list[dict[str, Any]] | None = None,
    priority: dict[str, Any] | None = None,
) -> str:
    """Produce a single actionable recommendation string."""
    bottlenecks = bottlenecks or []
    priority = priority or {}

    high_bottlenecks = [b for b in bottlenecks if b.get("severity") == "high"]
    if high_bottlenecks:
        affected = high_bottlenecks[0]["subsystem_id"]
        return (
            f"Restore the {affected} data pipeline: confirm DATABASE_URL, "
            "run the appropriate harvester, and verify table existence."
        )

    top_id = priority.get("subsystem_id", "")
    if top_id == "knowledge_graph":
        return "Index additional orchid taxa relationships into the Knowledge Graph to close entity-relationship gaps."
    if top_id == "pollinators":
        return "Run the GloBI pollinator harvester to expand orchid-pollinator relationship coverage."
    if top_id == "mycorrhiza":
        return "Ingest mycorrhizal dataset records to improve fungal relationship coverage."
    if top_id == "literature":
        return "Extract relationships from unprocessed literature documents to build scientific evidence."
    if top_id == "atlas":
        return "Import GBIF occurrence records to improve atlas geographic coverage."

    return "Review Mission Control subsystem health and prioritize the lowest-coverage adapter."


def recommended_owner(
    adapters: dict[str, dict[str, Any]],
    priority: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the recommended owner and action based on the top priority."""
    priority = priority or {}
    top_id = priority.get("subsystem_id", "knowledge_graph")
    owner_map = {
        "knowledge_graph": {"owner": "Scientific Data Lead", "action": "Approve Knowledge Graph indexing run"},
        "atlas": {"owner": "Atlas Data Lead", "action": "Approve GBIF occurrence import"},
        "literature": {"owner": "Literature Lead", "action": "Approve literature extraction pipeline"},
        "pollinators": {"owner": "Ecology Lead", "action": "Approve GloBI pollinator harvester"},
        "mycorrhiza": {"owner": "Ecology Lead", "action": "Approve mycorrhizal data ingestion"},
        "vision": {"owner": "Media Lead", "action": "Approve iNaturalist image harvester"},
        "grant_office": {"owner": "PI / Scientific Director", "action": "Review grant opportunities and approve publications"},
    }
    return owner_map.get(top_id, {"owner": "Scientific Director", "action": "Review subsystem health and authorize next action"})


def grant_opportunities(adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Derive actionable grant opportunities from current data maturity."""
    grant = adapters.get("grant_office", {})
    opportunities_count = to_int(grant.get("opportunities"))
    kg = adapters.get("knowledge_graph", {})
    lit = adapters.get("literature", {})

    opportunities = []

    if to_int(kg.get("relationships")) >= 1000:
        opportunities.append({
            "id": "kg-network-grant",
            "title": "Orchid Ecological Network Mapping Grant",
            "reason": "Knowledge Graph contains sufficient relationships to support a network-ecology grant application.",
            "readiness": "ready" if to_int(kg.get("relationships")) >= 10000 else "emerging",
        })

    if to_int(lit.get("documents")) >= 100:
        opportunities.append({
            "id": "lit-synthesis-grant",
            "title": "Literature Synthesis and Meta-Analysis Grant",
            "reason": "Literature corpus is large enough to support a systematic review grant.",
            "readiness": "ready" if to_int(lit.get("documents")) >= 1000 else "emerging",
        })

    if opportunities_count > 0 and not opportunities:
        opportunities.append({
            "id": "general-orchid-grant",
            "title": "Orchid Conservation Research Grant",
            "reason": "Baseline data available; additional data maturity will unlock targeted grant opportunities.",
            "readiness": "emerging",
        })

    return opportunities


def publication_opportunities(adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Identify subsystems with enough data to support a publication."""
    publications = []

    kg = adapters.get("knowledge_graph", {})
    if to_int(kg.get("entities")) >= 500 and to_int(kg.get("relationships")) >= 1000:
        publications.append({
            "id": "kg-data-paper",
            "title": "Orchid Continuum Knowledge Graph — Data Paper",
            "reason": "Entity and relationship counts meet the threshold for a data paper submission.",
        })

    atlas = adapters.get("atlas", {})
    if to_int(atlas.get("occurrences")) >= 10000:
        publications.append({
            "id": "atlas-range-paper",
            "title": "Orchid Range Map — Biogeographic Analysis",
            "reason": f"Atlas contains {to_int(atlas.get('occurrences')):,} occurrences sufficient for a range analysis paper.",
        })

    lit = adapters.get("literature", {})
    if to_int(lit.get("extracted_relationships")) >= 500:
        publications.append({
            "id": "lit-review-paper",
            "title": "Orchid–Pollinator Interaction Literature Review",
            "reason": "Extracted relationships corpus supports a comprehensive literature review.",
        })

    return publications


def research_risks(adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Surface research risks based on data coverage and availability."""
    risks = []

    kg = adapters.get("knowledge_graph", {})
    if not kg.get("available"):
        risks.append({"id": "kg-unavailable", "severity": "high", "description": "Knowledge Graph is unavailable; this blocks downstream analyses."})
    elif to_int(kg.get("relationships")) == 0:
        risks.append({"id": "kg-empty", "severity": "high", "description": "Knowledge Graph has no relationships; ecological networks cannot be analysed."})

    pollinators = adapters.get("pollinators", {})
    mycorrhiza = adapters.get("mycorrhiza", {})
    if not pollinators.get("available") and not mycorrhiza.get("available"):
        risks.append({"id": "ecology-unavailable", "severity": "high", "description": "Both pollinator and mycorrhizal data are unavailable; ecological completeness is severely impaired."})

    lit = adapters.get("literature", {})
    if not lit.get("available"):
        risks.append({"id": "lit-unavailable", "severity": "medium", "description": "Literature system is unavailable; evidence-based claim extraction is blocked."})

    atlas = adapters.get("atlas", {})
    if not atlas.get("available"):
        risks.append({"id": "atlas-unavailable", "severity": "medium", "description": "Atlas is unavailable; geographic range analyses cannot be performed."})

    return risks


# ---------------------------------------------------------------------------
# Phase 3 — Aggregate intelligence payload
# ---------------------------------------------------------------------------


def derive_mission_control_intelligence(adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Build the full Phase-3 intelligence payload from live adapter data."""
    priority = highest_scientific_priority(adapters)
    gap = largest_knowledge_gap(adapters)
    active = most_active_subsystem(adapters)
    completed = recently_completed_work(adapters)
    bottlenecks = data_collection_bottlenecks(adapters)
    action = suggested_next_action(adapters, bottlenecks=bottlenecks, priority=priority)
    owner = recommended_owner(adapters, priority=priority)
    grants = grant_opportunities(adapters)
    publications = publication_opportunities(adapters)
    risks = research_risks(adapters)

    return {
        "highest_scientific_priority": priority,
        "largest_knowledge_gap": gap,
        "most_active_subsystem": active,
        "recently_completed_work": completed,
        "data_collection_bottlenecks": bottlenecks,
        "suggested_next_action": action,
        "recommended_owner": owner,
        "grant_opportunities": grants,
        "publication_opportunities": publications,
        "research_risks": risks,
    }
