from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException

from app.multimodal_intelligence.routes import (
    ReviewDecisionRequest,
    _reviewer_from_auth,
    router,
)
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


def test_review_identity_is_derived_from_signed_owner_session() -> None:
    assert _reviewer_from_auth({"auth_type": "owner_session", "actor": "owner"}) == "owner"
    assert "reviewer" not in ReviewDecisionRequest.model_fields


@pytest.mark.parametrize(
    "auth,code",
    [
        ({"auth_type": "api_key", "actor": "backend_api_key"}, "HUMAN_REVIEW_OWNER_SESSION_REQUIRED"),
        ({"auth_type": "owner_session", "actor": ""}, "HUMAN_REVIEW_IDENTITY_REQUIRED"),
    ],
)
def test_review_identity_fails_closed_for_nonhuman_or_missing_identity(
    auth: dict[str, object], code: str
) -> None:
    with pytest.raises(HTTPException) as error:
        _reviewer_from_auth(auth)
    assert error.value.status_code == 403
    assert error.value.detail["code"] == code
