from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.semantic_index.routes as semantic_index_routes
from app.calyx_conversation.interaction_discovery_ingest import (
    ingest_globi_interactions_for_canonical_dataset,
)
from app.interaction_discovery.routes import router
from app.interaction_discovery.service import discover_interactions
from app.semantic_index.memory_repository import MemoryIndexRepository
from app.semantic_index.provider import DeterministicLocalProvider
from app.semantic_index.service import SemanticIndexService


def _fresh_repository(monkeypatch) -> None:
    """Isolate each test's semantic-index state.

    app.semantic_index.routes caches REPO/SERVICE as module globals, shared
    across the whole test session; monkeypatching a fresh in-memory
    repository per test keeps GloBI documents from one test visible to
    another.
    """
    repository = MemoryIndexRepository()
    service = SemanticIndexService(repository, DeterministicLocalProvider())
    monkeypatch.setattr(semantic_index_routes, "REPO", repository)
    monkeypatch.setattr(semantic_index_routes, "SERVICE", service)


def _ingest_sample(**overrides) -> dict:
    record = {
        "sourceTaxonName": "Orchis mascula",
        "sourceTaxonId": "GBIF:123",
        "interactionTypeName": "pollinatedBy",
        "targetTaxonName": "Bombus terrestris",
        "targetTaxonId": "GBIF:456",
        "referenceCitation": "Example study 2020",
        "sourceCitation": "GloBI dataset v1",
    }
    record.update(overrides)
    return ingest_globi_interactions_for_canonical_dataset([record], dataset_version="globi-2026-08")


def client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_discover_interactions_surfaces_ingested_globi_candidate(monkeypatch):
    _fresh_repository(monkeypatch)
    result = _ingest_sample()
    assert result["status"] == "indexed_for_research"

    discovery = discover_interactions(taxon="Orchis mascula")

    assert discovery["count"] == 1
    assert discovery["review_bound"] is True
    assert discovery["knowledge_graph_mutation"] is False
    record = discovery["interactions"][0]
    assert record["source_taxon_name"] == "Orchis mascula"
    assert record["target_taxon_name"] == "Bombus terrestris"
    assert record["interaction_type"] == "pollinatedBy"
    assert record["study_citation"] == "Example study 2020"
    assert record["dataset_version"] == "globi-2026-08"
    assert record["verification_state"] == "UNVERIFIED"
    assert "pollinator" in record["categories"]


def test_discover_interactions_filters_by_category(monkeypatch):
    _fresh_repository(monkeypatch)
    _ingest_sample()
    _ingest_sample(
        sourceTaxonName="Orchis mascula",
        interactionTypeName="hasHost",
        targetTaxonName="Rhizoctonia sp.",
        targetTaxonId="GBIF:789",
    )

    pollinator_only = discover_interactions(category="pollinator")
    mycorrhizal_only = discover_interactions(category="mycorrhizal")

    assert pollinator_only["count"] == 1
    assert pollinator_only["interactions"][0]["target_taxon_name"] == "Bombus terrestris"
    assert mycorrhizal_only["count"] == 1
    assert mycorrhizal_only["interactions"][0]["target_taxon_name"] == "Rhizoctonia sp."


def test_discover_interactions_taxon_filter_matches_either_side(monkeypatch):
    _fresh_repository(monkeypatch)
    _ingest_sample()

    by_target = discover_interactions(taxon="Bombus")

    assert by_target["count"] == 1


def test_discover_interactions_never_reports_knowledge_graph_mutation(monkeypatch):
    """No matter what's ingested, this read-only surface cannot claim a graph write happened."""
    _fresh_repository(monkeypatch)
    _ingest_sample()

    discovery = discover_interactions()

    assert discovery["knowledge_graph_mutation"] is False
    assert all(record["knowledge_graph_mutation"] is False for record in discovery["interactions"])


def test_discovery_endpoint_is_public_and_returns_interactions(monkeypatch):
    _fresh_repository(monkeypatch)
    _ingest_sample()
    api = client()

    response = api.get("/api/interactions/discovery", params={"taxon": "Orchis"})

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["interactions"][0]["source_taxon_name"] == "Orchis mascula"


def test_discovery_endpoint_rejects_invalid_category(monkeypatch):
    _fresh_repository(monkeypatch)
    api = client()

    response = api.get("/api/interactions/discovery", params={"category": "not-a-real-category"})

    assert response.status_code == 422


def test_discovery_endpoint_empty_when_nothing_ingested(monkeypatch):
    _fresh_repository(monkeypatch)
    api = client()

    response = api.get("/api/interactions/discovery")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 0
    assert body["interactions"] == []
