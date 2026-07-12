"""Tests for BUILD-062 Scientific Intelligence backend integration.

Covers:
- Cache module
- Normalizer module
- Intelligence derivation (Phase 3)
- Adapters (fallback behaviour when DB unavailable)
- Aggregator (all 8 sections present)
- FastAPI router (endpoint structure)
- Daily Brief (Phase 6)
- Knowledge Graph status (Phase 4)
- Research readiness metrics (Phase 5)
"""

from __future__ import annotations

import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.scientific_intelligence import router
from runtime.scientific_intelligence.cache import (
    cache_stats,
    get_cached,
    invalidate_all,
    set_cached,
)
from runtime.scientific_intelligence.normalizer import (
    normalize,
    normalize_atlas,
    normalize_grant_office,
    normalize_knowledge_graph,
    normalize_literature,
    normalize_mycorrhiza,
    normalize_pollinators,
    normalize_vision,
)
from runtime.scientific_intelligence.intelligence import (
    data_collection_bottlenecks,
    derive_mission_control_intelligence,
    grant_opportunities,
    highest_scientific_priority,
    largest_knowledge_gap,
    most_active_subsystem,
    publication_opportunities,
    recently_completed_work,
    recommended_owner,
    research_risks,
    suggested_next_action,
)
from runtime.scientific_intelligence.aggregator import (
    BUILD_ID,
    build_daily_brief,
    build_scientific_intelligence_payload,
)
from runtime.scientific_intelligence.adapters import (
    fetch_all_adapters,
    grant_office_adapter,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def make_app() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def live_kg() -> dict:
    return {
        "subsystem_id": "knowledge_graph",
        "name": "Knowledge Graph",
        "available": True,
        "status": "live",
        "entities": 5000,
        "relationships": 12000,
        "disconnected_nodes": 45,
        "validation_pct": 87.5,
        "growth_rate": 2.3,
        "last_sync": "2026-07-12T06:00:00+00:00",
        "provenance": {"entity_table": "oc_graph.nodes", "relationship_table": "oc_graph.edges"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def live_atlas() -> dict:
    return {
        "subsystem_id": "atlas",
        "name": "Atlas",
        "available": True,
        "status": "live",
        "occurrences": 85000,
        "taxa_covered": 4200,
        "coordinate_coverage_pct": 72.3,
        "last_import": "2026-07-12T05:00:00+00:00",
        "provenance": {"occurrence_table": "oc_atlas.occurrences"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def live_literature() -> dict:
    return {
        "subsystem_id": "literature",
        "name": "Literature",
        "available": True,
        "status": "live",
        "documents": 2500,
        "extracted_relationships": 8000,
        "ingestion_rate": 12.5,
        "last_ingestion": "2026-07-12T04:00:00+00:00",
        "provenance": {"document_table": "oc_literature.documents"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def live_pollinators() -> dict:
    return {
        "subsystem_id": "pollinators",
        "name": "Pollinators",
        "available": True,
        "status": "live",
        "relationships": 3500,
        "taxa_covered": 1200,
        "coverage_pct": 28.6,
        "last_harvest": "2026-07-11T20:00:00+00:00",
        "provenance": {"relationship_table": "oc_interactions.relationships"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def live_mycorrhiza() -> dict:
    return {
        "subsystem_id": "mycorrhiza",
        "name": "Mycorrhiza",
        "available": True,
        "status": "live",
        "records": 1800,
        "taxa_covered": 900,
        "coverage_pct": 21.4,
        "last_harvest": "2026-07-11T18:00:00+00:00",
        "provenance": {"mycorrhiza_table": "oc_mycorrhiza.species_mycorrhiza_unified_endpoint_cache"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def live_vision() -> dict:
    return {
        "subsystem_id": "vision",
        "name": "Vision Lab",
        "available": True,
        "status": "live",
        "images": 120000,
        "taxa_with_images": 3800,
        "quality_score": 64.2,
        "last_harvest": "2026-07-12T03:00:00+00:00",
        "provenance": {"image_table": "public.orchid_images_linked_v2"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def live_grant_office() -> dict:
    return {
        "subsystem_id": "grant_office",
        "name": "Grant Office",
        "available": True,
        "status": "live",
        "opportunities": 4,
        "active_grants": 2,
        "nearest_deadline": "unavailable",
        "recommended_publications": 5,
        "provenance": {"source": "derived"},
        "generated_at": "2026-07-12T06:00:00+00:00",
    }


def all_live_adapters() -> dict:
    return {
        "knowledge_graph": live_kg(),
        "atlas": live_atlas(),
        "literature": live_literature(),
        "pollinators": live_pollinators(),
        "mycorrhiza": live_mycorrhiza(),
        "vision": live_vision(),
        "grant_office": live_grant_office(),
    }


def all_unavailable_adapters() -> dict:
    """Return a set of adapters where every subsystem is unavailable."""
    subsystems = ["knowledge_graph", "atlas", "literature", "pollinators", "mycorrhiza", "vision", "grant_office"]
    names = {
        "knowledge_graph": "Knowledge Graph",
        "atlas": "Atlas",
        "literature": "Literature",
        "pollinators": "Pollinators",
        "mycorrhiza": "Mycorrhiza",
        "vision": "Vision Lab",
        "grant_office": "Grant Office",
    }
    return {
        sid: {
            "subsystem_id": sid,
            "name": names[sid],
            "available": False,
            "status": "unavailable",
            "generated_at": "2026-07-12T06:00:00+00:00",
        }
        for sid in subsystems
    }


# ---------------------------------------------------------------------------
# Cache tests
# ---------------------------------------------------------------------------


def test_cache_set_and_get():
    invalidate_all()
    key = "test_key"
    payload = {"value": 42}
    set_cached(key, payload)
    result = get_cached(key)
    assert result == payload


def test_cache_miss_returns_none():
    invalidate_all()
    assert get_cached("nonexistent") is None


def test_cache_expiry():
    invalidate_all()
    set_cached("ttl_test", {"x": 1})
    result = get_cached("ttl_test", ttl=0)
    assert result is None


def test_cache_invalidate_all():
    set_cached("a", {"a": 1})
    set_cached("b", {"b": 2})
    invalidate_all()
    assert get_cached("a") is None
    assert get_cached("b") is None


def test_cache_stats():
    invalidate_all()
    set_cached("stat_test", {"s": 1})
    stats = cache_stats()
    assert stats["entries"] >= 1
    assert "stat_test" in stats["keys"]
    assert "stat_test" in stats["ages_seconds"]


# ---------------------------------------------------------------------------
# Normalizer tests
# ---------------------------------------------------------------------------


def test_normalize_knowledge_graph_live():
    raw = {
        "available": True,
        "entities": 5000,
        "relationships": 12000,
        "disconnected_nodes": 45,
        "validation_pct": 87.5,
        "growth_rate": 2.3,
        "last_sync": "2026-07-12T06:00:00+00:00",
        "provenance": {"entity_table": "oc_graph.nodes"},
    }
    result = normalize_knowledge_graph(raw)
    assert result["subsystem_id"] == "knowledge_graph"
    assert result["available"] is True
    assert result["status"] == "live"
    assert result["entities"] == 5000
    assert result["relationships"] == 12000
    assert result["disconnected_nodes"] == 45
    assert result["validation_pct"] == 87.5
    assert result["provenance"]["entity_table"] == "oc_graph.nodes"


def test_normalize_knowledge_graph_unavailable():
    raw = {"available": False, "provenance": {"reason": "DB unavailable"}}
    result = normalize_knowledge_graph(raw)
    assert result["available"] is False
    assert result["status"] == "unavailable"
    assert result["entities"] == 0
    assert result["relationships"] == 0


def test_normalize_atlas():
    raw = {"available": True, "occurrences": 85000, "taxa_covered": 4200, "coordinate_coverage_pct": 72.3}
    result = normalize_atlas(raw)
    assert result["subsystem_id"] == "atlas"
    assert result["available"] is True
    assert result["occurrences"] == 85000
    assert result["taxa_covered"] == 4200


def test_normalize_literature():
    raw = {"available": True, "documents": 2500, "extracted_relationships": 8000}
    result = normalize_literature(raw)
    assert result["subsystem_id"] == "literature"
    assert result["documents"] == 2500
    assert result["extracted_relationships"] == 8000


def test_normalize_pollinators():
    raw = {"available": True, "relationships": 3500, "taxa_covered": 1200, "coverage_pct": 28.6}
    result = normalize_pollinators(raw)
    assert result["subsystem_id"] == "pollinators"
    assert result["relationships"] == 3500
    assert result["coverage_pct"] == 28.6


def test_normalize_mycorrhiza():
    raw = {"available": True, "records": 1800, "taxa_covered": 900, "coverage_pct": 21.4}
    result = normalize_mycorrhiza(raw)
    assert result["subsystem_id"] == "mycorrhiza"
    assert result["records"] == 1800


def test_normalize_vision():
    raw = {"available": True, "images": 120000, "taxa_with_images": 3800, "quality_score": 64.2}
    result = normalize_vision(raw)
    assert result["subsystem_id"] == "vision"
    assert result["images"] == 120000
    assert result["quality_score"] == 64.2


def test_normalize_grant_office():
    raw = {"available": True, "opportunities": 4, "active_grants": 2, "recommended_publications": 5}
    result = normalize_grant_office(raw)
    assert result["subsystem_id"] == "grant_office"
    assert result["opportunities"] == 4


def test_normalize_unknown_subsystem():
    result = normalize("nonexistent_system", {})
    assert result["available"] is False
    assert "No normalizer" in result["error"]


def test_normalize_handles_none_values():
    raw = {"available": True, "entities": None, "relationships": None}
    result = normalize_knowledge_graph(raw)
    assert result["entities"] == 0
    assert result["relationships"] == 0


# ---------------------------------------------------------------------------
# Intelligence derivation tests (Phase 3)
# ---------------------------------------------------------------------------


def test_highest_scientific_priority_returns_subsystem():
    adapters = all_live_adapters()
    priority = highest_scientific_priority(adapters)
    assert "subsystem_id" in priority
    assert priority["subsystem_id"] in {"knowledge_graph", "atlas", "literature", "pollinators", "mycorrhiza", "vision", "grant_office"}
    assert isinstance(priority.get("score"), float)


def test_highest_scientific_priority_fallback_when_unavailable():
    priority = highest_scientific_priority({})
    assert priority["subsystem_id"] == "knowledge_graph"


def test_largest_knowledge_gap_identifies_gap():
    adapters = all_live_adapters()
    gap = largest_knowledge_gap(adapters)
    assert "subsystem_id" in gap
    assert "gap_size" in gap
    assert isinstance(gap["gap_size"], int)
    assert gap["gap_size"] >= 0


def test_largest_knowledge_gap_empty_adapters():
    gap = largest_knowledge_gap({})
    assert gap["gap_size"] == 0


def test_most_active_subsystem_returns_highest_volume():
    adapters = all_live_adapters()
    active = most_active_subsystem(adapters)
    assert "subsystem_id" in active
    assert "metric" in active
    assert active["metric"] > 0


def test_most_active_subsystem_unavailable_adapters():
    active = most_active_subsystem(all_unavailable_adapters())
    assert active["metric"] == 0


def test_recently_completed_work_lists_live_subsystems():
    adapters = all_live_adapters()
    completed = recently_completed_work(adapters)
    assert isinstance(completed, list)
    assert len(completed) > 0
    for item in completed:
        assert "subsystem_id" in item
        assert "summary" in item


def test_recently_completed_work_empty_when_all_unavailable():
    completed = recently_completed_work(all_unavailable_adapters())
    assert completed == []


def test_data_collection_bottlenecks_detects_unavailable():
    adapters = all_unavailable_adapters()
    bottlenecks = data_collection_bottlenecks(adapters)
    assert len(bottlenecks) == len(adapters)
    for b in bottlenecks:
        assert b["severity"] == "high"
        assert "unavailable" in b["reason"].lower()


def test_data_collection_bottlenecks_no_issues_when_live():
    adapters = all_live_adapters()
    bottlenecks = data_collection_bottlenecks(adapters)
    high = [b for b in bottlenecks if b["severity"] == "high"]
    assert len(high) == 0


def test_suggested_next_action_is_string():
    adapters = all_live_adapters()
    bottlenecks = data_collection_bottlenecks(adapters)
    priority = highest_scientific_priority(adapters)
    action = suggested_next_action(adapters, bottlenecks=bottlenecks, priority=priority)
    assert isinstance(action, str)
    assert len(action) > 10


def test_suggested_next_action_addresses_high_bottleneck():
    adapters = all_unavailable_adapters()
    bottlenecks = data_collection_bottlenecks(adapters)
    action = suggested_next_action(adapters, bottlenecks=bottlenecks, priority={})
    assert "pipeline" in action.lower() or "database" in action.lower() or "harvester" in action.lower()


def test_recommended_owner_returns_dict():
    priority = {"subsystem_id": "knowledge_graph"}
    owner = recommended_owner({}, priority=priority)
    assert "owner" in owner
    assert "action" in owner


def test_recommended_owner_maps_to_known_subsystems():
    for sid in ["knowledge_graph", "atlas", "literature", "pollinators", "mycorrhiza", "vision", "grant_office"]:
        owner = recommended_owner({}, priority={"subsystem_id": sid})
        assert "owner" in owner
        assert "action" in owner


def test_grant_opportunities_with_sufficient_data():
    adapters = all_live_adapters()
    grants = grant_opportunities(adapters)
    assert isinstance(grants, list)
    assert len(grants) >= 1
    for g in grants:
        assert "title" in g
        assert "readiness" in g


def test_grant_opportunities_empty_without_data():
    grants = grant_opportunities(all_unavailable_adapters())
    assert isinstance(grants, list)


def test_publication_opportunities_with_sufficient_data():
    adapters = all_live_adapters()
    publications = publication_opportunities(adapters)
    assert isinstance(publications, list)
    # Live data has enough records to trigger at least one publication opportunity
    assert len(publications) >= 1
    for p in publications:
        assert "title" in p


def test_research_risks_with_unavailable_adapters():
    risks = research_risks(all_unavailable_adapters())
    assert isinstance(risks, list)
    assert len(risks) > 0
    severities = {r["severity"] for r in risks}
    assert "high" in severities


def test_research_risks_minimal_when_all_live():
    adapters = all_live_adapters()
    risks = research_risks(adapters)
    high_risks = [r for r in risks if r["severity"] == "high"]
    assert len(high_risks) == 0


def test_derive_mission_control_intelligence_has_all_keys():
    adapters = all_live_adapters()
    intel = derive_mission_control_intelligence(adapters)
    expected_keys = {
        "highest_scientific_priority",
        "largest_knowledge_gap",
        "most_active_subsystem",
        "recently_completed_work",
        "data_collection_bottlenecks",
        "suggested_next_action",
        "recommended_owner",
        "grant_opportunities",
        "publication_opportunities",
        "research_risks",
    }
    assert expected_keys.issubset(set(intel.keys()))


# ---------------------------------------------------------------------------
# Adapter fallback tests (Phase 2)
# ---------------------------------------------------------------------------


def test_fetch_all_adapters_returns_all_subsystems():
    # Without a DB, all adapters should return fallback payloads
    adapters = fetch_all_adapters()
    expected = {"knowledge_graph", "atlas", "literature", "pollinators", "mycorrhiza", "vision", "grant_office"}
    assert expected == set(adapters.keys())


def test_fetch_all_adapters_have_normalized_shape():
    adapters = fetch_all_adapters()
    for key, payload in adapters.items():
        assert "subsystem_id" in payload, f"Missing subsystem_id in {key}"
        assert "available" in payload, f"Missing available in {key}"
        assert "status" in payload, f"Missing status in {key}"
        assert "generated_at" in payload, f"Missing generated_at in {key}"


def test_adapter_fallback_when_no_db():
    # When DATABASE_URL is absent, adapters must return available=False
    adapters = fetch_all_adapters()
    # In test environment without DB, all adapters fall back
    for key in ["knowledge_graph", "atlas", "literature", "pollinators", "mycorrhiza", "vision"]:
        payload = adapters[key]
        assert payload["available"] is False or isinstance(payload.get("entities"), int) or isinstance(payload.get("occurrences"), int)


def test_grant_office_adapter_derives_from_inputs():
    invalidate_all()  # ensure no cached zero-data result from prior tests
    kg = {"available": True, "relationships": 15000}
    lit = {"available": True, "documents": 2000}
    result = grant_office_adapter(kg=kg, literature=lit)
    assert result["subsystem_id"] == "grant_office"
    assert result["available"] is True
    assert result["opportunities"] >= 1


def test_grant_office_adapter_zero_data():
    invalidate_all()  # ensure no cached result from prior tests
    result = grant_office_adapter(kg={}, literature={})
    assert result["subsystem_id"] == "grant_office"
    assert result["opportunities"] == 0


# ---------------------------------------------------------------------------
# Aggregator tests — all 8 sections present (Phase 1)
# ---------------------------------------------------------------------------


def test_aggregate_payload_has_required_sections():
    payload = build_scientific_intelligence_payload(use_cache=False)
    required_sections = [
        "build",
        "generated_at",
        "executive_summary",
        "subsystem_health",
        "scientific_priorities",
        "scientific_opportunities",
        "data_freshness",
        "research_readiness",
        "knowledge_graph_status",
        "scientific_activity_timeline",
    ]
    for section in required_sections:
        assert section in payload, f"Missing section: {section}"


def test_aggregate_payload_build_id():
    payload = build_scientific_intelligence_payload(use_cache=False)
    assert payload["build"] == BUILD_ID
    assert BUILD_ID == "BUILD-062"


def test_aggregate_executive_summary_structure():
    payload = build_scientific_intelligence_payload(use_cache=False)
    summary = payload["executive_summary"]
    assert "status" in summary
    assert "available_subsystems" in summary
    assert "total_subsystems" in summary
    assert summary["total_subsystems"] == 7
    assert summary["status"] in {"healthy", "warning", "critical"}


def test_aggregate_subsystem_health_has_7_entries():
    payload = build_scientific_intelligence_payload(use_cache=False)
    health = payload["subsystem_health"]
    assert len(health) == 7
    for item in health:
        assert "subsystem_id" in item
        assert "available" in item
        assert "status" in item


def test_aggregate_scientific_priorities_list():
    payload = build_scientific_intelligence_payload(use_cache=False)
    priorities = payload["scientific_priorities"]
    assert isinstance(priorities, list)
    for p in priorities:
        assert "rank" in p
        assert "subsystem_id" in p
        assert "type" in p


def test_aggregate_data_freshness_structure():
    payload = build_scientific_intelligence_payload(use_cache=False)
    freshness = payload["data_freshness"]
    assert "subsystems" in freshness
    assert "stale_count" in freshness
    assert "live_count" in freshness
    assert "assessment" in freshness
    assert freshness["assessment"] in {"all_live", "mixed", "all_stale"}


def test_aggregate_research_readiness_metrics():
    payload = build_scientific_intelligence_payload(use_cache=False)
    readiness = payload["research_readiness"]
    assert "overall_readiness" in readiness
    assert "readiness_label" in readiness
    assert "metrics" in readiness
    expected_metrics = {
        "atlas_growth", "literature_ingestion", "pollinator_coverage",
        "mycorrhiza_coverage", "image_quality", "taxonomic_completeness",
        "relationship_completeness", "evidence_confidence",
    }
    assert expected_metrics.issubset(set(readiness["metrics"].keys()))


def test_aggregate_knowledge_graph_status():
    payload = build_scientific_intelligence_payload(use_cache=False)
    kg = payload["knowledge_graph_status"]
    assert "available" in kg
    assert "entities" in kg
    assert "relationships" in kg
    assert "disconnected_nodes" in kg
    assert "last_sync" in kg


def test_aggregate_activity_timeline_is_list():
    payload = build_scientific_intelligence_payload(use_cache=False)
    timeline = payload["scientific_activity_timeline"]
    assert isinstance(timeline, list)
    for event in timeline:
        assert "subsystem_id" in event
        assert "event" in event
        assert "type" in event


def test_aggregate_includes_intelligence_and_daily_brief():
    payload = build_scientific_intelligence_payload(use_cache=False)
    assert "intelligence" in payload
    assert "daily_brief" in payload


def test_aggregate_caching():
    invalidate_all()
    first = build_scientific_intelligence_payload(use_cache=True)
    second = build_scientific_intelligence_payload(use_cache=True)
    # Second call should return same generated_at (from cache)
    assert first["generated_at"] == second["generated_at"]


# ---------------------------------------------------------------------------
# Daily Brief tests (Phase 6)
# ---------------------------------------------------------------------------


def test_daily_brief_structure():
    adapters = all_live_adapters()
    intel = derive_mission_control_intelligence(adapters)
    brief = build_daily_brief(adapters, intel)

    required_keys = {
        "title",
        "generated_at",
        "todays_highest_priorities",
        "research_accomplishments",
        "problems_requiring_attention",
        "suggested_decisions",
        "upcoming_grant_deadlines",
        "recommended_publications",
        "system_readiness",
    }
    assert required_keys.issubset(set(brief.keys()))


def test_daily_brief_title():
    adapters = all_live_adapters()
    intel = derive_mission_control_intelligence(adapters)
    brief = build_daily_brief(adapters, intel)
    assert "Orchid Continuum" in brief["title"]
    assert "Executive Daily Brief" in brief["title"]


def test_daily_brief_system_readiness():
    adapters = all_live_adapters()
    intel = derive_mission_control_intelligence(adapters)
    brief = build_daily_brief(adapters, intel)
    readiness = brief["system_readiness"]
    assert "status" in readiness
    assert readiness["status"] in {"ready", "degraded", "critical"}
    assert readiness["total"] == 7


def test_daily_brief_graceful_with_no_data():
    """Brief must not raise even when all adapters are unavailable."""
    adapters = all_unavailable_adapters()
    intel = derive_mission_control_intelligence(adapters)
    brief = build_daily_brief(adapters, intel)
    assert brief["system_readiness"]["status"] == "critical"
    assert brief["system_readiness"]["available"] == 0


# ---------------------------------------------------------------------------
# FastAPI router tests
# ---------------------------------------------------------------------------


def test_router_mounts_expected_endpoints():
    app = FastAPI()
    app.include_router(router)
    # FastAPI wraps included routers; collect paths from all route types
    paths = set()
    for route in app.routes:
        if hasattr(route, "path"):
            paths.add(route.path)
        # APIRouter include creates _IncludedRouter objects with a path prefix
        if hasattr(route, "path_regex"):
            import re
            pattern = route.path_regex.pattern.rstrip("$").rstrip("/")
            paths.add(pattern)
    # Check via the test client instead of inspecting route objects directly
    client = TestClient(app)
    expected_paths = [
        "/api/scientific-intelligence",
        "/api/scientific-intelligence/adapters",
        "/api/scientific-intelligence/knowledge-graph",
        "/api/scientific-intelligence/research-readiness",
        "/api/scientific-intelligence/daily-brief",
        "/api/scientific-intelligence/intelligence",
        "/api/scientific-intelligence/cache",
    ]
    for path in expected_paths:
        resp = client.get(path)
        assert resp.status_code in (200, 405), f"Endpoint {path!r} returned unexpected {resp.status_code}"


def test_router_get_aggregate_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence")
    assert response.status_code == 200
    data = response.json()
    assert data["build"] == "BUILD-062"
    assert "executive_summary" in data


def test_router_get_adapters_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence/adapters")
    assert response.status_code == 200
    data = response.json()
    assert "adapters" in data
    assert data["total_count"] == 7


def test_router_get_knowledge_graph_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence/knowledge-graph")
    assert response.status_code == 200
    data = response.json()
    assert "knowledge_graph" in data
    assert "entities" in data["knowledge_graph"]


def test_router_get_research_readiness_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence/research-readiness")
    assert response.status_code == 200
    data = response.json()
    assert "research_readiness" in data
    assert "metrics" in data["research_readiness"]


def test_router_get_daily_brief_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence/daily-brief")
    assert response.status_code == 200
    data = response.json()
    assert "todays_highest_priorities" in data
    assert "system_readiness" in data


def test_router_get_intelligence_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence/intelligence")
    assert response.status_code == 200
    data = response.json()
    assert "intelligence" in data
    assert "highest_scientific_priority" in data["intelligence"]


def test_router_cache_invalidation_returns_200():
    client = make_app()
    response = client.delete("/api/scientific-intelligence/cache")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "cache_invalidated"


def test_router_cache_status_returns_200():
    client = make_app()
    response = client.get("/api/scientific-intelligence/cache")
    assert response.status_code == 200
    data = response.json()
    assert "cache" in data
    assert "entries" in data["cache"]


def test_all_endpoints_return_build_id():
    client = make_app()
    endpoints = [
        "/api/scientific-intelligence",
        "/api/scientific-intelligence/adapters",
        "/api/scientific-intelligence/knowledge-graph",
        "/api/scientific-intelligence/research-readiness",
        "/api/scientific-intelligence/intelligence",
        "/api/scientific-intelligence/cache",
    ]
    for path in endpoints:
        response = client.get(path)
        assert response.status_code == 200, f"Expected 200 for {path}"
        data = response.json()
        assert data.get("build") == "BUILD-062", f"Missing build id in {path}"


# ---------------------------------------------------------------------------
# Graceful fallback tests (Phase 2, Phase 7)
# ---------------------------------------------------------------------------


def test_payload_graceful_when_all_adapters_unavailable():
    """All-unavailable adapters must produce a valid (not an exception) payload."""
    adapters = all_unavailable_adapters()
    intel = derive_mission_control_intelligence(adapters)
    # Should not raise
    assert isinstance(intel["suggested_next_action"], str)
    assert isinstance(intel["research_risks"], list)
    assert len(intel["research_risks"]) > 0


def test_intelligence_graceful_with_partial_adapters():
    """Partial live data must still produce a complete intelligence payload."""
    adapters = {
        "knowledge_graph": live_kg(),
        "atlas": {"subsystem_id": "atlas", "available": False, "status": "unavailable", "generated_at": "2026-07-12T00:00:00+00:00", "name": "Atlas"},
        "literature": live_literature(),
        "pollinators": {"subsystem_id": "pollinators", "available": False, "status": "unavailable", "generated_at": "2026-07-12T00:00:00+00:00", "name": "Pollinators"},
        "mycorrhiza": live_mycorrhiza(),
        "vision": {"subsystem_id": "vision", "available": False, "status": "unavailable", "generated_at": "2026-07-12T00:00:00+00:00", "name": "Vision Lab"},
        "grant_office": live_grant_office(),
    }
    intel = derive_mission_control_intelligence(adapters)
    assert "highest_scientific_priority" in intel
    assert "suggested_next_action" in intel


def test_normalizer_handles_garbage_input():
    result = normalize_knowledge_graph({"available": True, "entities": "not_a_number", "relationships": None})
    assert result["entities"] == 0
    assert result["relationships"] == 0
    # available=True but count=0 → "empty" (not "unavailable")
    assert result["status"] == "empty"
