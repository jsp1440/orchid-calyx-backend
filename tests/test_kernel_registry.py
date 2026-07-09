from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.kernel_registry import KernelRegistryService
from runtime.kernel_router import router


def test_kernel_registers_required_applications() -> None:
    service = KernelRegistryService()
    applications = {app.name: app for app in service.applications()}

    for name in [
        "Mission Control",
        "Atlas",
        "Species Explorer",
        "Knowledge Graph",
        "Vision Lab",
        "Grant Office",
        "Research Workspace",
        "University",
        "Conservatory",
        "Settings",
    ]:
        assert name in applications
        assert applications[name].route
        assert applications[name].repository
        assert applications[name].permissions


def test_capabilities_are_queryable_by_application_and_text() -> None:
    service = KernelRegistryService()

    atlas_capabilities = service.query_capabilities(application_id="atlas")
    assert {cap.capability_key for cap in atlas_capabilities} >= {
        "explore-regions",
        "habitat-viewer",
        "occurrence-search",
        "image-browser",
        "climate-layers",
    }

    health_capabilities = service.query_capabilities(query="health")
    assert any(cap.application_id == "mission-control" for cap in health_capabilities)


def test_kernel_health_includes_governance_and_counts() -> None:
    health = KernelRegistryService().health()

    assert health.status == "kernel_registry_ready"
    assert health.registry_counts["applications"] >= 10
    assert health.registry_counts["services"] >= 9
    assert health.registry_counts["integrations"] >= 18
    assert health.governance.policy_count >= 1
    assert health.governance.constitutional_status


def test_kernel_router_exposes_read_only_endpoints() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    for path, key in [
        ("/api/kernel/applications", "applications"),
        ("/api/kernel/services", "services"),
        ("/api/kernel/capabilities", "capabilities"),
        ("/api/kernel/integrations", "integrations"),
        ("/api/kernel/builds", "builds"),
    ]:
        response = client.get(path)
        assert response.status_code == 200
        assert key in response.json()
        assert response.json()[key]

    response = client.get("/api/kernel/health")
    assert response.status_code == 200
    assert response.json()["status"] == "kernel_registry_ready"


def test_kernel_capability_endpoint_filters() -> None:
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.get("/api/kernel/capabilities", params={"application_id": "atlas", "query": "image"})

    assert response.status_code == 200
    capabilities = response.json()["capabilities"]
    assert capabilities
    assert all(capability["application_id"] == "atlas" for capability in capabilities)
    assert any(capability["capability_key"] == "image-browser" for capability in capabilities)
