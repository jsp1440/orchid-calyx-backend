from __future__ import annotations

from fastapi import FastAPI

from app.multimodal_intelligence.routes import router
from app.multimodal_intelligence.status import capability_status


def test_capability_status_is_fail_closed() -> None:
    status = capability_status()
    assert status["production_ready"] is False
    assert status["safety"]["live_inference_enabled"] is False
    assert status["safety"]["automatic_species_identification"] is False
    assert status["safety"]["human_review_required"] is True
    assert set(status["lanes"]) == {"literature", "matrix", "vision"}


def test_status_router_is_registered_and_protected() -> None:
    app = FastAPI()
    app.include_router(router)
    route = next(
        route
        for route in app.routes
        if getattr(route, "path", None) == "/api/mission-control/multimodal-intelligence/status"
    )
    assert "GET" in route.methods
    assert route.dependant.dependencies
