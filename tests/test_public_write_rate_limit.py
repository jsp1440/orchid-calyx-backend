"""The public-write brake: bounded, per-client, per-route-family, honest about being in-process."""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import rate_limit
from app.community_observation import routes as community_routes
from app.community_observation import service as community_service
from app.constituent_platform import service as constituent_service
from app.constituent_platform.routes import router as constituent_router
from app.field_hypotheses.routes import hypothesis_router, observation_router
from app.rate_limit import SlidingWindowLimiter, public_write_rate_limit
from app.routers.health import add_mission_control_cors_headers


class Clock:
    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_up_to_the_limit_then_refuses_with_retry_after_and_recovers():
    clock = Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    for _ in range(3):
        assert limiter.check("a", limit=3, window_seconds=60) == (True, 0)
    allowed, retry_after = limiter.check("a", limit=3, window_seconds=60)
    assert allowed is False
    assert 1 <= retry_after <= 61
    # Another client is unaffected; a zero limit disables the brake.
    assert limiter.check("b", limit=3, window_seconds=60) == (True, 0)
    assert limiter.check("a", limit=0, window_seconds=60) == (True, 0)
    clock.now += 61
    assert limiter.check("a", limit=3, window_seconds=60) == (True, 0)


def test_limiter_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(rate_limit, "MAX_TRACKED_CLIENTS", 10)
    clock = Clock()
    limiter = SlidingWindowLimiter(clock=clock)
    for index in range(50):
        limiter.check(f"client-{index}", limit=5, window_seconds=60)
        clock.now += 0.01
    assert len(limiter._events) <= 10


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.delenv("CALYX_API_KEY", raising=False)
    monkeypatch.setenv("PUBLIC_WRITE_RATE_LIMIT", "2")
    monkeypatch.setenv("PUBLIC_WRITE_RATE_WINDOW_SECONDS", "600")
    rate_limit.LIMITER.reset()
    constituent_service.configure_store(constituent_service.memory_store())
    community_service.configure_store(community_service.memory_store())
    application = FastAPI()
    application.include_router(constituent_router)
    application.include_router(community_routes.router)
    application.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    yield application
    rate_limit.LIMITER.reset()
    constituent_service.configure_store(None)
    community_service.configure_store(None)


def test_public_constituent_writes_share_one_allowance_per_client(app):
    client = TestClient(app)
    assert client.post("/api/constituent/subscribe", json={"email": "a@example.com"}).status_code == 200
    assert client.post("/api/constituent/unsubscribe", json={"email": "a@example.com"}).status_code == 200
    third = client.post(
        "/api/constituent/contact",
        json={"email": "a@example.com", "body": "A real message of enough length."},
    )
    assert third.status_code == 429
    assert third.headers["Retry-After"].isdigit()
    assert "Too many submissions" in third.json()["detail"]
    # Reads are never braked.
    assert client.get("/api/constituent/newsletter/archive").status_code == 200


def test_community_submissions_have_their_own_allowance_and_clients_are_separate(app):
    client = TestClient(app)
    payload = {
        "taxon_name_verbatim": "Cattleya labiata",
        "location_verbatim": "Serra do Mar, Brazil",
        "observation_date": "2026-06-15",
        "epistemic_label": "PROBABLE",
    }
    assert client.post("/api/constituent/subscribe", json={"email": "a@example.com"}).status_code == 200
    assert client.post("/api/constituent/subscribe", json={"email": "b@example.com"}).status_code == 200
    # The constituent allowance is spent, but community submissions are a separate family.
    assert client.post("/api/community/observations", json=payload).status_code == 200
    assert client.post("/api/community/observations", json=payload).status_code == 200
    assert client.post("/api/community/observations", json=payload).status_code == 429
    # A different forwarded client address has a fresh allowance.
    other = client.post(
        "/api/community/observations", json=payload, headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"}
    )
    assert other.status_code == 200
    assert len(community_service.CommunityObservationRepository(community_service.get_store()).list()) == 3


def test_brake_can_be_disabled_by_configuration(app, monkeypatch):
    monkeypatch.setenv("PUBLIC_WRITE_RATE_LIMIT", "0")
    client = TestClient(app)
    for _ in range(5):
        assert client.post("/api/constituent/unsubscribe", json={"email": "z@example.com"}).status_code == 200


def test_dependency_is_attached_to_exactly_the_public_write_routes():
    braked = {
        (route.path, method)
        for route in [
            *constituent_router.routes,
            *community_routes.router.routes,
            *observation_router.routes,
            *hypothesis_router.routes,
        ]
        for method in getattr(route, "methods", set())
        if any(
            getattr(dep.dependency, "__name__", "").startswith("public_write_rate_limit_")
            for dep in getattr(route, "dependencies", [])
        )
    }
    assert braked == {
        ("/api/constituent/subscribe", "POST"),
        ("/api/constituent/unsubscribe", "POST"),
        ("/api/constituent/contact", "POST"),
        ("/api/community/observations", "POST"),
        ("/api/field-observations/{observation_id}/hypotheses", "POST"),
        ("/api/field-hypotheses/{hypothesis_id}/evidence", "POST"),
    }


def test_dependency_factory_produces_distinct_named_callables():
    a = public_write_rate_limit("alpha")
    b = public_write_rate_limit("beta")
    assert a is not b
    assert a.__name__ == "public_write_rate_limit_alpha"
    assert Depends(a).dependency is a
