from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.calyx_conversation.interaction_discovery_ingest import (
    ingest_globi_interactions_for_canonical_dataset,
)
from app.interaction_discovery.routes import router
from app.interaction_discovery.service import discover_interactions
from app.semantic_index import repository_runtime
from app.semantic_index.memory_repository import MemoryIndexRepository


def _fresh_repository(monkeypatch) -> None:
    """Isolate each test's semantic-index state.

    The semantic-index runtime is shared across the whole test session;
    replacing it with a fresh activated in-memory runtime keeps GloBI
    documents from one test visible to another.
    """
    repository = MemoryIndexRepository()
    runtime = repository_runtime.SemanticIndexRepositoryRuntime(database_url="")
    runtime._activate(repository)
    monkeypatch.setattr(repository_runtime, "RUNTIME", runtime)


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


class _FakeDurableRepository(MemoryIndexRepository):
    """In-memory stand-in exposing the transactional surface of the Postgres repository."""

    def atomic(self, operation):
        return operation()

    def refresh_for_read(self):
        return None


def _durable_repository(monkeypatch) -> None:
    runtime = repository_runtime.SemanticIndexRepositoryRuntime(database_url="postgresql://fake-durable-index/test")
    runtime._activate(_FakeDurableRepository())
    monkeypatch.setattr(repository_runtime, "RUNTIME", runtime)


def test_unprovisioned_index_is_labelled_so_empty_is_not_absence(monkeypatch):
    _fresh_repository(monkeypatch)

    body = client().get("/api/interactions/discovery", params={"taxon": "Dendrobium nobile"}).json()

    assert body["status"] == "ok"
    assert body["count"] == 0
    assert body["index_state"] == "memory_unprovisioned"
    assert "not evidence that no interactions are known" in body["index_note"]


def test_durable_index_is_labelled_durable_without_unprovisioned_note(monkeypatch):
    _durable_repository(monkeypatch)
    _ingest_sample()

    body = client().get("/api/interactions/discovery", params={"taxon": "Orchis"}).json()

    assert body["index_state"] == "durable"
    assert body["index_note"] is None
    assert body["count"] == 1


def test_durable_index_empty_result_is_still_durable(monkeypatch):
    _durable_repository(monkeypatch)

    body = client().get("/api/interactions/discovery", params={"taxon": "Nothing here"}).json()

    assert body["count"] == 0
    assert body["index_state"] == "durable"
    assert body["index_note"] is None


def test_configured_but_unreachable_durable_index_returns_503_not_empty_ok(monkeypatch):
    runtime = repository_runtime.SemanticIndexRepositoryRuntime(database_url="postgresql://fake-durable-index/test")

    def _unreachable():
        raise ConnectionError("database down")

    monkeypatch.setattr(runtime, "_build_repository", _unreachable)
    monkeypatch.setattr(repository_runtime, "RUNTIME", runtime)

    response = client().get("/api/interactions/discovery")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SEMANTIC_INDEX_DATABASE_UNAVAILABLE"


def test_memory_repository_is_not_durable_even_when_database_url_configured(monkeypatch):
    """Negative control: a non-transactional repository never reports durable."""
    runtime = repository_runtime.SemanticIndexRepositoryRuntime(database_url="postgresql://fake-durable-index/test")
    runtime._activate(MemoryIndexRepository())
    monkeypatch.setattr(repository_runtime, "RUNTIME", runtime)

    assert discover_interactions()["index_state"] == "memory_unprovisioned"


def test_revision_id_string_is_exact_beyond_javascript_safe_integer(monkeypatch):
    _fresh_repository(monkeypatch)
    _ingest_sample()

    response = client().get("/api/interactions/discovery", params={"taxon": "Orchis"})
    record = response.json()["interactions"][0]

    assert record["revision_id"] > 2**53
    assert record["revision_id_str"] == str(record["revision_id"])
    # The raw JSON text carries the full integer; the string form survives a
    # float64 round-trip where the integer would not.
    assert f'"revision_id":{record["revision_id"]}' in response.text.replace(" ", "")
    assert int(float(record["revision_id"])) != record["revision_id"]
    assert int(record["revision_id_str"]) == record["revision_id"]


def test_discovery_response_schema_declares_index_state_and_revision_id_str():
    schema = client().get("/openapi.json").json()
    components = schema["components"]["schemas"]
    response_schema = components["InteractionDiscoveryResponse"]
    record_schema = components["InteractionDiscoveryRecord"]

    assert "index_state" in response_schema["required"]
    assert set(response_schema["properties"]["index_state"]["enum"]) == {"durable", "memory_unprovisioned"}
    assert "index_note" in response_schema["properties"]
    assert "revision_id" in record_schema["properties"]
    assert "revision_id_str" in record_schema["properties"]
    route = schema["paths"]["/api/interactions/discovery"]["get"]
    assert route["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("InteractionDiscoveryResponse")


def test_response_model_keeps_every_legacy_field(monkeypatch):
    _fresh_repository(monkeypatch)
    _ingest_sample()

    body = client().get("/api/interactions/discovery").json()

    for key in ("status", "count", "total_matched", "truncated", "category", "taxon_filter",
                "review_bound", "knowledge_graph_mutation", "note", "interactions"):
        assert key in body
    legacy_record_keys = {
        "source_taxon_name", "source_taxon_id", "target_taxon_name", "target_taxon_id", "interaction_type",
        "categories", "study_citation", "study_source_citation", "study_external_id", "provider",
        "provider_stability", "dataset_version", "verification_state", "knowledge_graph_mutation",
        "revision_id", "locator",
    }
    assert legacy_record_keys <= set(body["interactions"][0])
