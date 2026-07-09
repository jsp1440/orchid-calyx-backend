"""Read-only FastAPI endpoints for the Orchid Continuum Kernel."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from .kernel_registry import KernelRegistryService, as_payload


router = APIRouter(prefix="/api/kernel", tags=["Orchid Continuum Kernel"])


def service() -> KernelRegistryService:
    return KernelRegistryService()


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
