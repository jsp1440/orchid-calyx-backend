"""Regression test for a real production gap: app.atlas_intelligence.api's
router was fully implemented and tested (test_atlas_registry_api.py builds
its own bare TestClient(FastAPI()) directly around the module) but was
never imported or include_router()'d anywhere reachable from app.main - the
actual deployed FastAPI application (`uvicorn app.main:app`). Every request
to /atlas/* in production returned 404.

matrix_identification (all 8 router files), matrix_relationship, and
multimodal_intelligence are NOT part of this gap - despite an initial
audit's shallow-clone-limited grep suggesting otherwise, they are already
reachable through app.main: app.routers.health.router and
app.routers.reference_docs.router both nest include_router() calls for
these modules one level deep, and both of those routers are themselves
included directly by app.main. This suite verifies that continues to be
true (a regression here would be just as real a production break as
atlas_intelligence's original gap), alongside the actual fix.

This asserts directly against app.main.app's route table rather than by
issuing HTTP requests and checking status codes: app.main installs a global
"http" middleware (see the `@app.middleware("http")` above the route
definitions) that returns 401 for *any* unmatched `/api/*` path before
FastAPI's router even gets a chance to 404 - confirmed empirically while
diagnosing this gap. An HTTP-status-based reachability test would
therefore silently pass even when a router is not mounted at all.
Inspecting app.routes directly has no such blind spot: a route is either
present in the table or it isn't. atlas_intelligence's /atlas/status is the
one endpoint here with no auth dependency at all, so it also gets one real
HTTP-level check - a 200 there cannot be produced by the auth-fallback
middleware, which returns 401, never 200.
"""
from __future__ import annotations

from app.main import app

_ROUTE_PATHS = {route.path for route in app.routes if hasattr(route, "path")}
_ROUTE_TAGS = {
    tag
    for route in app.routes
    if hasattr(route, "tags")
    for tag in (route.tags or [])
}


def test_matrix_identification_router_is_registered() -> None:
    assert "matrix-identification" in _ROUTE_TAGS
    assert "/api/matrix-identification/contract" in _ROUTE_PATHS


def test_matrix_identification_session_router_is_registered() -> None:
    assert "matrix-identification-sessions" in _ROUTE_TAGS
    assert "/api/matrix-identification/sessions" in _ROUTE_PATHS
    assert "/api/matrix-identification/sessions/{session_id}/observations" in _ROUTE_PATHS
    assert "/api/matrix-identification/sessions/{session_id}/evaluate" in _ROUTE_PATHS


def test_matrix_identification_explanation_router_is_registered() -> None:
    assert "matrix-identification-explanations" in _ROUTE_TAGS
    assert "/api/matrix-identification/sessions/{session_id}/explain" in _ROUTE_PATHS


def test_matrix_identification_vision_router_is_registered() -> None:
    assert "matrix-identification-vision" in _ROUTE_TAGS
    assert "/api/matrix-identification/sessions/{session_id}/vision/suggestions" in _ROUTE_PATHS


def test_matrix_identification_report_router_is_registered() -> None:
    assert "matrix-identification-reports" in _ROUTE_TAGS
    assert "/api/matrix-identification/sessions/{session_id}/reports" in _ROUTE_PATHS


def test_matrix_identification_registry_router_is_registered() -> None:
    assert "matrix-identification-registry" in _ROUTE_TAGS
    assert "/api/matrix-identification/registry" in _ROUTE_PATHS


def test_matrix_identification_registry_persistence_router_is_registered() -> None:
    assert "matrix-identification-registry-persistence" in _ROUTE_TAGS
    assert "/api/matrix-identification/registry/persistence-status" in _ROUTE_PATHS


def test_matrix_identification_durability_readiness_router_is_registered() -> None:
    assert "matrix-identification-durability-readiness" in _ROUTE_TAGS
    assert "/api/matrix-identification/persistence-readiness" in _ROUTE_PATHS


def test_matrix_relationship_router_is_registered() -> None:
    assert "matrix-relationship" in _ROUTE_TAGS
    assert "/api/matrix-relationship/contract" in _ROUTE_PATHS
    assert "/api/matrix-relationship/build" in _ROUTE_PATHS


def test_atlas_intelligence_router_is_registered() -> None:
    assert "atlas" in _ROUTE_TAGS
    assert "/atlas/status" in _ROUTE_PATHS


def test_multimodal_intelligence_router_is_registered() -> None:
    assert "multimodal-intelligence" in _ROUTE_TAGS
    assert "/api/mission-control/multimodal-intelligence/status" in _ROUTE_PATHS


def test_atlas_status_endpoint_is_actually_public_end_to_end() -> None:
    """The only one of these endpoints with no auth dependency at all -
    worth one real HTTP-level check, since a 200 here cannot be produced by
    the global auth-fallback middleware (which returns 401, never 200)."""
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/atlas/status")
    assert response.status_code == 200
    assert response.json()["service"] == "atlas-planetary-intelligence"
