"""#1652 — OC_CONSTITUENT_PERSISTENCE picks exactly one authoritative store and fails closed."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import rate_limit
from app.constituent_platform import canonical_store as cs
from app.constituent_platform import service as legacy
from app.constituent_platform.routes import get_service, owner_router, router
from app.routers.health import add_mission_control_cors_headers


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    for name in ("CALYX_API_KEY", "CONSTITUENT_MANAGE_SECRET", "CALYX_OWNER_SESSION_SECRET", "PUBLIC_WRITE_RATE_LIMIT"):
        monkeypatch.delenv(name, raising=False)
    memory = legacy.memory_store()
    legacy.configure_store(memory)
    cs.configure_canonical_service(None)
    rate_limit.LIMITER.reset()
    yield memory
    legacy.configure_store(None)
    cs.configure_canonical_service(None)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.include_router(owner_router)
    app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    return TestClient(app)


@pytest.mark.parametrize("value", [None, "", "research_station", " Research_Station "])
def test_default_and_explicit_research_station_use_the_legacy_service(monkeypatch, value):
    if value is None:
        monkeypatch.delenv(cs.PERSISTENCE_ENV, raising=False)
    else:
        monkeypatch.setenv(cs.PERSISTENCE_ENV, value)
    assert type(get_service()) is legacy.ConstituentService


def test_canonical_without_database_url_fails_closed_and_never_falls_back(monkeypatch, isolated):
    monkeypatch.setenv(cs.PERSISTENCE_ENV, "canonical")
    monkeypatch.delenv("DATABASE_URL", raising=False)
    client = _client()
    resp = client.post("/api/constituent/subscribe", json={"email": "someone@example.com"})
    assert resp.status_code == 503
    detail = resp.json()["detail"]
    assert "DATABASE_URL" in detail
    assert "migrations/20260927b_constituent_newsletter_canonical.sql" in detail
    assert client.get("/api/constituent/newsletter/archive").status_code == 503
    assert isolated.list(owner_key=legacy.OWNER_KEY, project_id=legacy.PROJECT_SUBSCRIPTIONS, kind=legacy.KIND_SUBSCRIPTION) == []


def test_unknown_persistence_value_fails_closed(monkeypatch):
    monkeypatch.setenv(cs.PERSISTENCE_ENV, "both")
    resp = _client().post("/api/constituent/unsubscribe", json={"email": "someone@example.com"})
    assert resp.status_code == 503
    assert cs.PERSISTENCE_ENV in resp.json()["detail"]


def test_canonical_with_unreachable_database_fails_closed(monkeypatch):
    monkeypatch.setenv(cs.PERSISTENCE_ENV, "canonical")
    monkeypatch.setenv("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none?connect_timeout=1")
    resp = _client().get("/api/constituent/newsletter/archive")
    assert resp.status_code == 503
    assert "unreachable" in resp.json()["detail"]
