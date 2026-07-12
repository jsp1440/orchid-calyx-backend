"""BUILD-062 Scientific Intelligence API router.

Exposes:
  GET /api/scientific-intelligence          — aggregate payload (Phase 1)
  GET /api/scientific-intelligence/adapters — per-subsystem adapter status (Phase 2)
  GET /api/scientific-intelligence/knowledge-graph — KG statistics (Phase 4)
  GET /api/scientific-intelligence/research-readiness — research metrics (Phase 5)
  GET /api/scientific-intelligence/daily-brief — executive daily brief (Phase 6)
  GET /api/scientific-intelligence/intelligence — derived intelligence (Phase 3)
  DELETE /api/scientific-intelligence/cache — invalidate cache (owner-only)

All routes are read-only except the cache-invalidation route which is safe
and does not mutate any scientific data.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from runtime.scientific_intelligence.adapters import fetch_all_adapters
from runtime.scientific_intelligence.aggregator import (
    BUILD_ID,
    build_daily_brief,
    build_scientific_intelligence_payload,
    knowledge_graph_status,
    research_readiness,
)
from runtime.scientific_intelligence.cache import cache_stats, invalidate_all
from runtime.scientific_intelligence.intelligence import derive_mission_control_intelligence
from runtime.scientific_intelligence.utils import utc_now

router = APIRouter(prefix="/api/scientific-intelligence", tags=["scientific-intelligence"])


@router.get("")
def scientific_intelligence() -> dict[str, Any]:
    """Aggregate Scientific Intelligence payload — all 8 sections."""
    return build_scientific_intelligence_payload()


@router.get("/adapters")
def scientific_intelligence_adapters() -> dict[str, Any]:
    """Live status for all subsystem adapters (Phase 2)."""
    adapters = fetch_all_adapters()
    return {
        "build": BUILD_ID,
        "generated_at": utc_now(),
        "adapters": adapters,
        "available_count": sum(1 for a in adapters.values() if a.get("available")),
        "total_count": len(adapters),
    }


@router.get("/knowledge-graph")
def scientific_intelligence_knowledge_graph() -> dict[str, Any]:
    """Real Knowledge Graph statistics (Phase 4)."""
    adapters = fetch_all_adapters()
    return {
        "build": BUILD_ID,
        "generated_at": utc_now(),
        "knowledge_graph": knowledge_graph_status(adapters),
    }


@router.get("/research-readiness")
def scientific_intelligence_research_readiness() -> dict[str, Any]:
    """Live research intelligence metrics (Phase 5)."""
    adapters = fetch_all_adapters()
    intelligence = derive_mission_control_intelligence(adapters)
    return {
        "build": BUILD_ID,
        "generated_at": utc_now(),
        "research_readiness": research_readiness(adapters, intelligence),
    }


@router.get("/daily-brief")
def scientific_intelligence_daily_brief() -> dict[str, Any]:
    """Backend-driven Executive Daily Brief (Phase 6)."""
    adapters = fetch_all_adapters()
    intelligence = derive_mission_control_intelligence(adapters)
    brief = build_daily_brief(adapters, intelligence)
    return {"build": BUILD_ID, **brief}


@router.get("/intelligence")
def scientific_intelligence_derived() -> dict[str, Any]:
    """Phase 3 — derived Mission Control intelligence payload."""
    adapters = fetch_all_adapters()
    intelligence = derive_mission_control_intelligence(adapters)
    return {
        "build": BUILD_ID,
        "generated_at": utc_now(),
        "intelligence": intelligence,
    }


@router.get("/cache")
def scientific_intelligence_cache_status() -> dict[str, Any]:
    """Diagnostic: current cache state."""
    return {"build": BUILD_ID, "cache": cache_stats()}


@router.delete("/cache")
def scientific_intelligence_cache_invalidate() -> dict[str, Any]:
    """Invalidate all scientific intelligence caches (safe, non-destructive)."""
    invalidate_all()
    return {"build": BUILD_ID, "status": "cache_invalidated", "generated_at": utc_now()}
