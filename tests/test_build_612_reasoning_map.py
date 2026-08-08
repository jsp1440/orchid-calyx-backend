from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.brain import routes
from app.brain.reasoning_map import (
    ReasoningDirection,
    ReasoningMapEngine,
    ReasoningProfile,
    relation_semantics,
)
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node


def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        nodes=[
            Node(1, "gene", "gene:abc", "ABC1"),
            Node(2, "protein", "protein:abc1", "ABC1 protein"),
            Node(3, "physiology", "physiology:cell-expansion", "Cell expansion"),
            Node(4, "phenotype", "phenotype:leaf-size", "Leaf size"),
            Node(5, "environment", "environment:high-vpd", "High VPD"),
            Node(6, "habitat", "habitat:cloud-forest", "Cloud forest"),
        ],
        edges=[
            Edge(
                1,
                "activates",
                1,
                2,
                "paper_claim",
                "c1",
                "curated",
                0.90,
                "high",
                None,
                {"doi": "10.1/a"},
            ),
            Edge(
                2,
                "promotes",
                2,
                3,
                "paper_claim",
                "c2",
                "curated",
                0.80,
                "high",
                None,
                {"paper_id": "p2"},
            ),
            Edge(
                3,
                "results_in",
                3,
                4,
                "paper_claim",
                "c3",
                "curated",
                0.70,
                "high",
                None,
                {"citation": "Physiology study"},
            ),
            Edge(4, "inhibits", 5, 3, "paper_claim", "c4", "curated", 0.85, "high"),
            Edge(5, "occurs_in", 4, 6, "occurrence", "o1", "observed", 0.95, "high"),
            Edge(
                6,
                "regulates",
                3,
                2,
                "paper_claim",
                "cycle",
                "candidate",
                0.60,
                "medium",
            ),
        ],
    )


def client() -> TestClient:
    application = FastAPI()
    application.include_router(routes.router)
    application.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "tester"
    }
    application.dependency_overrides[routes.get_graph_repository] = graph
    return TestClient(application)


def test_relation_semantics_distinguish_promotion_inhibition_and_context():
    assert relation_semantics("promotes").polarity == 1
    assert relation_semantics("inhibits").polarity == -1
    assert relation_semantics("regulates").causal is True
    assert relation_semantics("occurs_in").role == "context"


def test_forward_reasoning_map_builds_multistep_biological_pathway():
    result = ReasoningMapEngine(graph()).build(
        1,
        direction=ReasoningDirection.FORWARD,
        profile=ReasoningProfile.BIOLOGICAL_MECHANISM,
        max_depth=4,
        causal_only=True,
    )

    deepest = next(path for path in result["paths"] if path["node_ids"] == [1, 2, 3, 4])
    assert deepest["predicates"] == ["activates", "promotes", "results_in"]
    assert deepest["confidence"] == 0.63175
    assert deepest["polarity"] == 1
    assert deepest["evidence"][0]["doi"] == "10.1/a"
    assert result["summary"]["causal_edge_count"] >= 3
    assert result["governance"]["canonical_graph_mutated"] is False


def test_backward_map_can_trace_environmental_cause_from_phenotype_pathway():
    result = ReasoningMapEngine(graph()).build(
        3,
        direction=ReasoningDirection.BACKWARD,
        profile=ReasoningProfile.PHENOTYPE_EXPRESSION,
        max_depth=2,
        causal_only=True,
    )
    paths = {tuple(path["node_ids"]): path for path in result["paths"]}
    assert (3, 5) in paths
    assert paths[(3, 5)]["polarity"] == -1
    assert paths[(3, 5)]["traversal_direction"] == "backward"


def test_cycle_protection_never_repeats_node_in_path():
    result = ReasoningMapEngine(graph()).build(
        1, max_depth=8, limit=100, causal_only=True
    )
    assert all(
        len(path["node_ids"]) == len(set(path["node_ids"])) for path in result["paths"]
    )


def test_causal_only_excludes_context_edges():
    result = ReasoningMapEngine(graph()).build(1, max_depth=6, causal_only=True)
    assert all(edge["edge_type"] != "occurs_in" for edge in result["edges"])


def test_reasoning_map_api_is_authenticated_and_read_only():
    api = client()
    response = api.post(
        "/brain/reasoning-map",
        json={
            "subject_node_id": 1,
            "profile": "biological_mechanism",
            "max_depth": 4,
            "causal_only": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["subject"]["canonical_key"] == "gene:abc"
    assert body["summary"]["path_count"] > 0
    assert body["governance"]["read_only"] is True


def test_reasoning_map_unknown_node_and_invalid_payload_fail_closed():
    api = client()
    assert (
        api.post("/brain/reasoning-map", json={"subject_node_id": 999}).status_code
        == 404
    )
    assert (
        api.post(
            "/brain/reasoning-map", json={"subject_node_id": 1, "max_depth": 99}
        ).status_code
        == 422
    )
