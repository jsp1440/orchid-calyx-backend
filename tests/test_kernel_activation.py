from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.kernel_activation import CalyxKernelOrchestrator, KernelDependencyGraphService, KernelQueryService
from runtime.kernel_registry import KernelRegistryService
from runtime.kernel_router import router


def test_kernel_query_services_find_operational_gaps() -> None:
    query = KernelQueryService(KernelRegistryService())

    assert any(item["id"] == "atlas" for item in query.find_applications("atlas"))
    assert any(item["id"] == "relationship-engine" for item in query.find_services("relationship"))
    assert any(item["id"] == "openai" for item in query.find_disconnected_integrations())
    assert any(item["build_number"] == "BUILD-041" for item in query.find_builds_waiting_on_dependencies())


def test_dependency_graph_exposes_application_service_integration_edges() -> None:
    graph_service = KernelDependencyGraphService(KernelRegistryService())
    graph = graph_service.graph()
    edge_pairs = {(edge.source_id, edge.target_id) for edge in graph.edges}

    assert ("mission-control", "fastapi") in edge_pairs
    assert ("atlas", "taxonomy-service") in edge_pairs
    assert ("taxonomy-service", "gbif") in edge_pairs

    traversal = graph_service.traverse("atlas")
    assert "taxonomy-service" in traversal["visited"]
    assert "gbif" in traversal["visited"]


def test_orchestrator_recommends_without_execution_authority() -> None:
    orchestrator = CalyxKernelOrchestrator(KernelRegistryService())

    planner = orchestrator.planner()
    assert planner["mode"] == "planning_only_no_execution"
    assert planner["recommended_next_build"]["build_number"] == "BUILD-041"
    assert planner["registry_completion_score"] > 0
    assert planner["service_maturity_score"] >= 0

    runtime = orchestrator.runtime()
    assert runtime["reasoning_context"]["execution_allowed"] is False
    assert runtime["reasoning_context"]["writes_allowed"] is False
    assert all(reference["exposed"] is False for reference in runtime["secrets_vault"])


def test_kernel_activation_router_endpoints() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    for path in [
        "/api/kernel/dependencies",
        "/api/kernel/planner",
        "/api/kernel/recommendations",
        "/api/kernel/tasks",
        "/api/kernel/governance",
        "/api/kernel/runtime",
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()

    dependency_response = client.get("/api/kernel/dependencies", params={"object_id": "atlas"})
    assert dependency_response.status_code == 200
    assert "taxonomy-service" in dependency_response.json()["visited"]

    query_response = client.get("/api/kernel/query", params={"kind": "services", "query": "telemetry"})
    assert query_response.status_code == 200
    assert any(item["id"] == "telemetry" for item in query_response.json()["services"])
