"""BUILD-069 read-only Knowledge Graph API contract tests.

Every test substitutes an in-memory repository. No database connection or graph
write is possible.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import knowledge_graph
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node, canonical_key


def _repo() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        [
            Node(1, "genus", canonical_key("genus", 560), "Cattleya",
                 "public.taxonomy_genus", "560", "curated", 1.0, "high"),
            Node(2, "taxon", canonical_key("taxon", 1001), "Cattleya labiata",
                 "public.taxonomy_species", "1001", "curated", 1.0, "high"),
            Node(3, "trait", canonical_key("trait", "t1"), "epiphyte",
                 "oc_views.trait_resolved_v4", "t1", "normalized", 0.9, "high"),
        ],
        [
            Edge(1, "genus_contains_species", 1, 2, "public.taxonomy_species",
                 "1001", "curated", 1.0, "high", "taxonomy_rule"),
            Edge(2, "has_trait", 2, 3, "oc_views.trait_resolved_v4", "t1",
                 "normalized", 0.9, "high", "traits_build"),
        ],
    )


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(knowledge_graph.router)
    return TestClient(app)


def test_genus_route_returns_depth_two_evidence_without_mutating_repo(monkeypatch):
    repo = _repo()
    before_nodes = repo.all_nodes()
    before_edges = repo.all_edges()
    monkeypatch.setattr(knowledge_graph, "_repo", lambda: repo)

    response = _client().get(
        "/api/knowledge-graph/genus/Cattleya",
        params={"depth": 2, "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["focal_node"]["label"] == "Cattleya"
    assert payload["domain_coverage"]["traits"] == {"nodes": 1, "edges": 1}
    assert repo.all_nodes() == before_nodes
    assert repo.all_edges() == before_edges


def test_genus_route_forwards_filters_and_pagination(monkeypatch):
    repo = _repo()
    calls: list[dict] = []
    original = repo.get_outgoing_edges

    def capture(node_ids, edge_types=None, limit=100, offset=0):
        calls.append({
            "node_ids": list(node_ids), "edge_types": set(edge_types or []),
            "limit": limit, "offset": offset,
        })
        return original(node_ids, edge_types=edge_types, limit=limit, offset=offset)

    monkeypatch.setattr(repo, "get_outgoing_edges", capture)
    monkeypatch.setattr(knowledge_graph, "_repo", lambda: repo)

    response = _client().get(
        "/api/knowledge-graph/genus/Cattleya",
        params={
            "depth": 1, "edge_types": "genus_contains_species",
            "node_types": "taxon", "limit": 1, "offset": 0,
        },
    )

    assert response.status_code == 200
    assert calls == [{
        "node_ids": [1], "edge_types": {"genus_contains_species"},
        "limit": 2, "offset": 0,
    }]
    assert response.json()["filters"] == {
        "node_types": ["taxon"], "edge_types": ["genus_contains_species"],
    }


def test_unknown_genus_returns_404(monkeypatch):
    monkeypatch.setattr(knowledge_graph, "_repo", _repo)
    response = _client().get("/api/knowledge-graph/genus/NotARealGenus")
    assert response.status_code == 404
    assert response.json() == {"detail": "Node not found in graph"}


def test_missing_database_configuration_returns_503(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = _client().get("/api/knowledge-graph/genus/Cattleya")
    assert response.status_code == 503
    assert response.json() == {"detail": "Knowledge Graph database not configured"}


def test_route_rejects_unbounded_parameters_before_repository_access(monkeypatch):
    def should_not_run():
        raise AssertionError("repository must not be constructed")

    monkeypatch.setattr(knowledge_graph, "_repo", should_not_run)
    client = _client()

    assert client.get(
        "/api/knowledge-graph/genus/Cattleya", params={"depth": 4},
    ).status_code == 422
    assert client.get(
        "/api/knowledge-graph/genus/Cattleya", params={"limit": 501},
    ).status_code == 422
    assert client.get(
        "/api/knowledge-graph/genus/Cattleya", params={"offset": -1},
    ).status_code == 422
