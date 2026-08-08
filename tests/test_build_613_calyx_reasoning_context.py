from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.calyx_conversation import reasoning_routes
from app.calyx_conversation.reasoning_routes import (
    CalyxReasoningMapRequest,
    compose_reasoning_answer,
    run_reasoning_map,
)
from app.security import verify_owner_or_api_key
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node


def graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        nodes=[
            Node(1, "environment", "environment:cool-night", "Cool night"),
            Node(2, "physiology", "physiology:respiration", "Respiration"),
            Node(3, "process", "process:carbohydrate", "Carbohydrate retention"),
            Node(4, "phenotype", "phenotype:flowering", "Flowering"),
        ],
        edges=[
            Edge(1, "reduces", 1, 2, "paper_claim", "p1", "curated", 0.90, "high"),
            Edge(2, "promotes", 2, 3, "paper_claim", "p2", "curated", 0.80, "high"),
            Edge(
                3,
                "promotes",
                3,
                4,
                "paper_claim",
                "p3",
                "curated",
                0.75,
                "high",
                None,
                {"doi": "10.1000/flowering"},
            ),
        ],
    )


def app(monkeypatch) -> TestClient:
    application = FastAPI()
    application.include_router(reasoning_routes.router)
    application.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "actor": "tester"
    }
    monkeypatch.setattr(reasoning_routes, "_graph_repository", graph)
    return TestClient(application)


def empty_retrieval() -> dict:
    return {
        "results": [],
        "total_eligible_results": 0,
        "retrieval_mode": "HYBRID",
        "ranking_configuration_version": "test",
    }


def test_reasoning_adapter_reuses_brain_engine_without_graph_mutation(monkeypatch):
    monkeypatch.setattr(reasoning_routes, "_graph_repository", graph)
    result = run_reasoning_map(
        CalyxReasoningMapRequest(
            subject_node_id=1,
            profile="phenotype_expression",
            max_depth=4,
            causal_only=True,
        )
    )
    deepest = next(path for path in result["paths"] if path["node_ids"] == [1, 2, 3, 4])
    assert deepest["predicates"] == ["reduces", "promotes", "promotes"]
    assert deepest["polarity"] == -1
    assert result["governance"]["canonical_graph_mutated"] is False


def test_reasoning_answer_exposes_inspectable_pathways_and_boundary(monkeypatch):
    monkeypatch.setattr(reasoning_routes, "_graph_repository", graph)
    reasoning = run_reasoning_map(CalyxReasoningMapRequest(subject_node_id=1))
    answer = compose_reasoning_answer(
        "Why might cool nights affect flowering?",
        reasoning,
        empty_retrieval(),
        pathway_limit=5,
    )
    assert "Cool night --reduces--> Respiration" in answer
    assert "graph pathway is an explanatory hypothesis structure, not proof of causality" in answer
    assert "Question: Why might cool nights affect flowering?" in answer


def test_direct_calyx_reasoning_map_endpoint_is_authenticated_and_read_only(monkeypatch):
    client = app(monkeypatch)
    response = client.post(
        "/calyx/reasoning-map",
        json={
            "subject_node_id": 1,
            "profile": "phenotype_expression",
            "causal_only": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["subject"]["canonical_key"] == "environment:cool-night"
    assert payload["summary"]["path_count"] >= 3
    assert payload["governance"]["read_only"] is True


def test_reasoning_query_combines_map_and_indexed_evidence(monkeypatch):
    client = app(monkeypatch)
    monkeypatch.setattr(
        reasoning_routes,
        "_retrieval",
        lambda message, mode, limit, internal_access: {
            "results": [
                {
                    "title": "Temperature and flowering physiology",
                    "object_type": "paper",
                    "verification_state": "verified",
                    "citation": {"document_title": "Orchid Physiology Review"},
                }
            ],
            "total_eligible_results": 1,
            "retrieval_mode": mode,
            "ranking_configuration_version": "test",
        },
    )
    response = client.post(
        "/calyx/reasoning-query",
        json={
            "message": "Why might cool nights affect flowering?",
            "subject_node_id": 1,
            "profile": "phenotype_expression",
            "causal_only": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert "Highest-priority inspectable pathways" in payload["answer"]
    assert "Temperature and flowering physiology" in payload["answer"]
    assert payload["reasoning_map"]["summary"]["path_count"] >= 3
    assert payload["epistemic_policy"]["reasoning_map_read_only"] is True
    assert payload["epistemic_policy"]["automatic_scientific_publication"] is False


def test_reasoning_endpoint_fails_closed_for_unknown_node(monkeypatch):
    client = app(monkeypatch)
    response = client.post("/calyx/reasoning-map", json={"subject_node_id": 999})
    assert response.status_code == 404
