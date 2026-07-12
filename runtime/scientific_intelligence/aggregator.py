"""BUILD-062 scientific intelligence aggregator.

Builds the complete payload for GET /api/scientific-intelligence by
composing all 8 response sections from live adapter data and the executive
engine.  Extends (does not replace) the BUILD-061 executive architecture.

Sections produced:
  1. executive_summary
  2. subsystem_health
  3. scientific_priorities
  4. scientific_opportunities
  5. data_freshness
  6. research_readiness
  7. knowledge_graph_status
  8. scientific_activity_timeline
"""

from __future__ import annotations

from typing import Any

from runtime.scientific_intelligence.adapters import fetch_all_adapters
from runtime.scientific_intelligence.cache import get_cached, set_cached
from runtime.scientific_intelligence.intelligence import (
    data_collection_bottlenecks,
    derive_mission_control_intelligence,
    grant_opportunities,
    highest_scientific_priority,
    publication_opportunities,
    research_risks,
)
from runtime.scientific_intelligence.utils import to_int, to_float, utc_now

BUILD_ID = "BUILD-062"
AGGREGATE_CACHE_KEY = "scientific_intelligence_aggregate"
AGGREGATE_CACHE_TTL = 60  # seconds


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------


def _executive_summary(adapters: dict[str, dict[str, Any]], intelligence: dict[str, Any]) -> dict[str, Any]:
    available_count = sum(1 for a in adapters.values() if a.get("available"))
    total_count = len(adapters)
    priority = intelligence.get("highest_scientific_priority", {})
    action = intelligence.get("suggested_next_action", "Review Mission Control for priorities.")
    risks = intelligence.get("research_risks", [])
    high_risks = [r for r in risks if r.get("severity") == "high"]

    health_label = "healthy" if available_count == total_count else ("warning" if available_count > 0 else "critical")
    return {
        "status": health_label,
        "available_subsystems": available_count,
        "total_subsystems": total_count,
        "highest_priority": priority.get("subsystem_id"),
        "priority_reason": priority.get("reason"),
        "suggested_action": action,
        "risk_count": len(risks),
        "high_risk_count": len(high_risks),
        "narrative": (
            f"{available_count}/{total_count} scientific subsystems are live. "
            f"Top priority: {priority.get('subsystem_id', 'unknown')}. "
            f"{len(high_risks)} high-severity risk(s) detected."
        ),
    }


def _subsystem_health(adapters: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for key, payload in adapters.items():
        rows.append({
            "subsystem_id": key,
            "name": payload.get("name", key),
            "available": payload.get("available", False),
            "status": payload.get("status", "unavailable"),
            "generated_at": payload.get("generated_at", utc_now()),
        })
    return rows


def _scientific_priorities(intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    priority = intelligence.get("highest_scientific_priority", {})
    gap = intelligence.get("largest_knowledge_gap", {})
    bottlenecks = intelligence.get("data_collection_bottlenecks", [])

    priorities = []
    if priority.get("subsystem_id"):
        priorities.append({
            "rank": 1,
            "subsystem_id": priority["subsystem_id"],
            "reason": priority.get("reason", ""),
            "score": priority.get("score", 0),
            "type": "scientific_priority",
        })
    if gap.get("subsystem_id"):
        priorities.append({
            "rank": 2,
            "subsystem_id": gap["subsystem_id"],
            "reason": gap.get("description", ""),
            "score": gap.get("gap_size", 0),
            "type": "knowledge_gap",
        })
    for i, bottleneck in enumerate(bottlenecks[:3], start=3):
        priorities.append({
            "rank": i,
            "subsystem_id": bottleneck["subsystem_id"],
            "reason": bottleneck.get("reason", ""),
            "score": 0,
            "type": "bottleneck",
        })
    return priorities


def _scientific_opportunities(intelligence: dict[str, Any]) -> list[dict[str, Any]]:
    grants = intelligence.get("grant_opportunities", [])
    publications = intelligence.get("publication_opportunities", [])
    opportunities = []
    for item in grants:
        opportunities.append({**item, "category": "grant"})
    for item in publications:
        opportunities.append({**item, "category": "publication"})
    return opportunities


def _data_freshness(adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    freshness_items = []
    for key, payload in adapters.items():
        last_updated = (
            payload.get("last_sync")
            or payload.get("last_import")
            or payload.get("last_ingestion")
            or payload.get("last_harvest")
            or "unavailable"
        )
        freshness_items.append({
            "subsystem_id": key,
            "name": payload.get("name", key),
            "last_updated": last_updated,
            "available": payload.get("available", False),
            "status": "live" if payload.get("available") else "stale",
        })
    stale_count = sum(1 for f in freshness_items if f["status"] == "stale")
    return {
        "subsystems": freshness_items,
        "stale_count": stale_count,
        "live_count": len(freshness_items) - stale_count,
        "assessment": "all_live" if stale_count == 0 else ("mixed" if stale_count < len(freshness_items) else "all_stale"),
    }


def research_readiness(adapters: dict[str, dict[str, Any]], intelligence: dict[str, Any]) -> dict[str, Any]:
    """Phase 5 — research intelligence metrics."""
    atlas = adapters.get("atlas", {})
    lit = adapters.get("literature", {})
    pollinators = adapters.get("pollinators", {})
    mycorrhiza = adapters.get("mycorrhiza", {})
    vision = adapters.get("vision", {})
    kg = adapters.get("knowledge_graph", {})

    atlas_growth = min(100, to_int(atlas.get("occurrences")) // 1000)
    lit_ingestion = min(100, to_int(lit.get("documents")) // 100)
    pollinator_coverage = min(100, int(to_float(pollinators.get("coverage_pct"))))
    mycorrhiza_coverage = min(100, int(to_float(mycorrhiza.get("coverage_pct"))))
    image_quality = min(100, int(to_float(vision.get("quality_score"))))
    kg_relationships = to_int(kg.get("relationships"))
    relationship_completeness = min(100, kg_relationships // 1000)
    entities = to_int(kg.get("entities"))
    taxonomic_completeness = min(100, entities // 100)
    evidence_confidence = min(100, int((to_int(lit.get("extracted_relationships")) / max(kg_relationships, 1)) * 100)) if kg_relationships > 0 else 0

    metrics = {
        "atlas_growth": atlas_growth,
        "literature_ingestion": lit_ingestion,
        "pollinator_coverage": pollinator_coverage,
        "mycorrhiza_coverage": mycorrhiza_coverage,
        "image_quality": image_quality,
        "taxonomic_completeness": taxonomic_completeness,
        "relationship_completeness": relationship_completeness,
        "evidence_confidence": evidence_confidence,
    }
    overall = round(sum(metrics.values()) / len(metrics), 1)
    return {
        "overall_readiness": overall,
        "readiness_label": "ready" if overall >= 70 else ("emerging" if overall >= 30 else "early"),
        "metrics": metrics,
    }


def knowledge_graph_status(adapters: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Phase 4 — real Knowledge Graph statistics."""
    kg = adapters.get("knowledge_graph", {})
    return {
        "available": kg.get("available", False),
        "entities": kg.get("entities", 0),
        "relationships": kg.get("relationships", 0),
        "disconnected_nodes": kg.get("disconnected_nodes", 0),
        "validation_pct": kg.get("validation_pct", 0.0),
        "growth_rate": kg.get("growth_rate", 0.0),
        "last_sync": kg.get("last_sync", "unavailable"),
        "status": kg.get("status", "unavailable"),
        "provenance": kg.get("provenance", {}),
    }


def _activity_timeline(adapters: dict[str, dict[str, Any]], generated_at: str) -> list[dict[str, Any]]:
    """Build a simple activity timeline from adapter states."""
    events = []
    for key, payload in adapters.items():
        if payload.get("available") and payload.get("status") == "live":
            events.append({
                "timestamp": generated_at,
                "subsystem_id": key,
                "event": f"{payload.get('name', key)} is live",
                "type": "live_data",
            })
        elif not payload.get("available"):
            events.append({
                "timestamp": generated_at,
                "subsystem_id": key,
                "event": f"{payload.get('name', key)} data unavailable",
                "type": "unavailable",
            })
    return events


# ---------------------------------------------------------------------------
# Phase 6 — Executive Daily Brief
# ---------------------------------------------------------------------------


def build_daily_brief(
    adapters: dict[str, dict[str, Any]],
    intelligence: dict[str, Any],
) -> dict[str, Any]:
    """Generate the backend-driven executive daily briefing."""
    priorities = [
        {
            "rank": i + 1,
            "subsystem_id": p["subsystem_id"],
            "reason": p.get("reason", ""),
        }
        for i, p in enumerate((_scientific_priorities(intelligence))[:3])
    ]

    completed = intelligence.get("recently_completed_work", [])
    risks = intelligence.get("research_risks", [])
    grants = intelligence.get("grant_opportunities", [])
    publications = intelligence.get("publication_opportunities", [])

    problems = [
        {"subsystem_id": r["id"], "description": r["description"], "severity": r["severity"]}
        for r in risks
        if r.get("severity") == "high"
    ]
    bottleneck_problems = [
        {"subsystem_id": b["subsystem_id"], "description": b["reason"], "severity": b["severity"]}
        for b in intelligence.get("data_collection_bottlenecks", [])
        if b.get("severity") == "high"
    ]
    all_problems = (problems + bottleneck_problems)[:5]

    owner = intelligence.get("recommended_owner", {})
    decisions = []
    if owner:
        decisions.append({
            "decision": owner.get("action"),
            "owner": owner.get("owner"),
            "urgency": "high" if all_problems else "normal",
        })

    available_count = sum(1 for a in adapters.values() if a.get("available"))
    total_count = len(adapters)
    system_readiness = "ready" if available_count == total_count else ("degraded" if available_count > 0 else "critical")

    return {
        "title": "Orchid Continuum Scientific Intelligence — Executive Daily Brief",
        "generated_at": utc_now(),
        "todays_highest_priorities": priorities,
        "research_accomplishments": [{"summary": c.get("summary", "")} for c in completed[:5]],
        "problems_requiring_attention": all_problems,
        "suggested_decisions": decisions,
        "upcoming_grant_deadlines": [
            {"title": g.get("title"), "readiness": g.get("readiness")} for g in grants[:3]
        ],
        "recommended_publications": [
            {"title": p.get("title")} for p in publications[:3]
        ],
        "system_readiness": {
            "status": system_readiness,
            "available": available_count,
            "total": total_count,
        },
    }


# ---------------------------------------------------------------------------
# Main aggregator
# ---------------------------------------------------------------------------


def build_scientific_intelligence_payload(use_cache: bool = True) -> dict[str, Any]:
    """Assemble the complete /api/scientific-intelligence response payload."""
    if use_cache:
        cached = get_cached(AGGREGATE_CACHE_KEY, AGGREGATE_CACHE_TTL)
        if cached is not None:
            return cached

    generated_at = utc_now()
    adapters = fetch_all_adapters()
    intelligence = derive_mission_control_intelligence(adapters)

    payload: dict[str, Any] = {
        "build": BUILD_ID,
        "generated_at": generated_at,
        "executive_summary": _executive_summary(adapters, intelligence),
        "subsystem_health": _subsystem_health(adapters),
        "scientific_priorities": _scientific_priorities(intelligence),
        "scientific_opportunities": _scientific_opportunities(intelligence),
        "data_freshness": _data_freshness(adapters),
        "research_readiness": research_readiness(adapters, intelligence),
        "knowledge_graph_status": knowledge_graph_status(adapters),
        "scientific_activity_timeline": _activity_timeline(adapters, generated_at),
        "intelligence": intelligence,
        "daily_brief": build_daily_brief(adapters, intelligence),
    }

    if use_cache:
        set_cached(AGGREGATE_CACHE_KEY, payload)

    return payload
