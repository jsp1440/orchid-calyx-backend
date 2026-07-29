from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brain import routes
from app.brain.connectors import ConnectorRegistry, ManifestConnector, default_registry
from app.brain.reasoning import RULES, InferenceEngine, InferenceType
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node


def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        nodes=[
            Node(1, "taxon", "taxon:a", "Orchid A"),
            Node(2, "habitat", "habitat:cloud", "Cloud forest"),
            Node(3, "taxon", "taxon:b", "Orchid B"),
            Node(4, "assessment", "assessment:a", "Endangered"),
        ],
        edges=[
            Edge(
                1,
                "occurs_in",
                1,
                2,
                "occurrence",
                "a-1",
                "observed",
                0.90,
                "high",
                None,
                {"doi": "10.1/a"},
            ),
            Edge(
                2,
                "occurs_in",
                3,
                2,
                "occurrence",
                "b-1",
                "observed",
                0.80,
                "high",
                None,
                {"citation": "Voucher B"},
            ),
            Edge(
                3,
                "has_conservation_assessment",
                1,
                4,
                "assessment",
                "red-list-a",
                "curated",
                1.0,
                "high",
            ),
        ],
    )


def client(repo=None) -> TestClient:
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "tester"
    }
    application.dependency_overrides[routes.get_graph_repository] = lambda: (
        repo or graph()
    )
    return TestClient(application)


def test_every_required_inference_has_a_deterministic_rule():
    assert set(RULES) == set(InferenceType)


def test_shared_target_inference_is_deterministic_and_evidence_bearing():
    engine = InferenceEngine(graph())
    first = engine.infer(1, InferenceType.HABITAT_SIMILARITY)
    second = engine.infer(1, InferenceType.HABITAT_SIMILARITY)

    assert first == second
    assert first["results"][0]["candidate_node_id"] == 3
    assert first["results"][0]["confidence"] == 0.72
    assert [
        item["edge_id"] for item in first["results"][0]["supporting_citations"]
    ] == [1, 2]
    assert first["governance"] == {
        "status": "candidate_inference",
        "automatically_published": False,
        "human_review_required": True,
    }


def test_direct_inference_preserves_source_evidence():
    result = InferenceEngine(graph()).infer(1, InferenceType.CONSERVATION_RISK)
    assert result["results"][0]["candidate_node_id"] == 4
    assert result["results"][0]["supporting_citations"][0]["source_pk"] == "red-list-a"


def test_connector_registry_rejects_duplicate_identity():
    registry = ConnectorRegistry()
    connector = ManifestConnector("module", "Module", "1", ("health",))
    registry.register(connector)
    try:
        registry.register(connector)
    except ValueError as exc:
        assert str(exc) == "CONNECTOR_ALREADY_REGISTERED"
    else:
        raise AssertionError("duplicate connector identity was accepted")


def test_default_registry_declares_all_literature_sources_without_network_calls():
    catalog = default_registry().catalog()
    assert {item["id"] for item in catalog} >= {
        "crossref",
        "openalex",
        "semantic-scholar",
        "pubmed",
        "gbif",
        "bhl",
        "jstor",
    }
    assert all(item["health"]["operational"] is False for item in catalog)


def test_brain_routes_are_authenticated_by_default():
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[routes.get_graph_repository] = graph
    assert TestClient(application).get("/brain/node/1").status_code == 401


def test_brain_node_relationship_query_and_inference_routes():
    api = client()
    assert api.get("/brain/node/1").json()["canonical_key"] == "taxon:a"
    relationships = api.get("/brain/relationships/1").json()["relationships"]
    assert [item["id"] for item in relationships] == [1, 3]

    inferred = api.post(
        "/brain/infer",
        json={
            "subject_node_id": 1,
            "inference_type": "habitat_similarity",
            "limit": 10,
        },
    )
    assert inferred.status_code == 200
    assert inferred.json()["results"][0]["candidate_node_id"] == 3

    queried = api.post("/brain/query", json={"node_type": "taxon", "limit": 10})
    assert queried.status_code == 200
    assert [item["id"] for item in queried.json()["nodes"]] == [1, 3]
    assert queried.json()["read_only"] is True


def test_connect_endpoint_only_permits_declared_safe_actions():
    api = client()
    result = api.post(
        "/brain/connect", json={"connector_id": "crossref", "action": "describe"}
    )
    assert result.status_code == 200
    assert result.json()["connector_id"] == "crossref"
    rejected = api.post(
        "/brain/connect", json={"connector_id": "crossref", "action": "execute"}
    )
    assert rejected.status_code == 422


def test_unknown_node_and_unconfigured_database_fail_closed(monkeypatch):
    assert client().get("/brain/node/999").status_code == 404
    monkeypatch.delenv("DATABASE_URL", raising=False)
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "tester"
    }
    response = TestClient(application).get("/brain/node/1")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "BRAIN_DATABASE_NOT_CONFIGURED"
