"""Read-only FastAPI endpoints for the Orchid Continuum Kernel."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from .kernel_activation import CalyxKernelOrchestrator, KernelDependencyGraphService, KernelQueryService
from .kernel_registry import KernelRegistryService, as_payload


router = APIRouter(prefix="/api/kernel", tags=["Orchid Continuum Kernel"])


def service() -> KernelRegistryService:
    return KernelRegistryService()


def orchestrator() -> CalyxKernelOrchestrator:
    return CalyxKernelOrchestrator(service())


@router.get("/applications")
def kernel_applications() -> dict[str, Any]:
    return {"applications": as_payload(service().applications())}


@router.get("/services")
def kernel_services() -> dict[str, Any]:
    return {"services": as_payload(service().services())}


@router.get("/capabilities")
def kernel_capabilities(
    query: str | None = Query(default=None),
    application_id: str | None = Query(default=None),
) -> dict[str, Any]:
    return {
        "capabilities": as_payload(
            service().query_capabilities(query=query, application_id=application_id)
        )
    }


@router.get("/integrations")
def kernel_integrations() -> dict[str, Any]:
    return {"integrations": as_payload(service().integrations())}


@router.get("/builds")
def kernel_builds() -> dict[str, Any]:
    return {"builds": as_payload(service().builds())}


@router.get("/health")
def kernel_health() -> dict[str, Any]:
    health = service().health()
    if hasattr(health, "model_dump"):
        return health.model_dump()
    return health.dict()


@router.get("/dependencies")
def kernel_dependencies(
    object_id: str | None = Query(default=None),
    max_depth: int = Query(default=4, ge=1, le=8),
) -> dict[str, Any]:
    graph_service = KernelDependencyGraphService(service())
    if object_id:
        return graph_service.traverse(object_id, max_depth=max_depth)
    graph = graph_service.graph()
    if hasattr(graph, "model_dump"):
        return graph.model_dump()
    return graph.dict()


@router.get("/planner")
def kernel_planner() -> dict[str, Any]:
    return orchestrator().planner()


@router.get("/recommendations")
def kernel_recommendations() -> dict[str, Any]:
    return orchestrator().recommendations()


@router.get("/tasks")
def kernel_tasks() -> dict[str, Any]:
    return orchestrator().tasks()


@router.get("/governance")
def kernel_governance() -> dict[str, Any]:
    return service().governance()


@router.get("/runtime")
def kernel_runtime() -> dict[str, Any]:
    return orchestrator().runtime()


@router.get("/query")
def kernel_query(
    kind: str | None = Query(default=None),
    query: str | None = Query(default=None),
) -> dict[str, Any]:
    return KernelQueryService(service()).query(kind=kind, query=query)
