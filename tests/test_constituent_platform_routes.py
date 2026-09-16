"""Focused tests for Journey 12 — constituent platform newsletter routes.

Tests use a minimal FastAPI app that mounts only the constituent_platform
router, bypassing the full app startup (no DATABASE_URL, no background jobs).
Security dependencies are overridden so tests don't require credentials.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.constituent_platform.domain import (
    CommunicationState,
    PreferenceState,
)
from app.constituent_platform.routes import router

# ---------------------------------------------------------------------------
# Test app fixture — minimal FastAPI app with constituent_platform router only
# ---------------------------------------------------------------------------


def _make_app() -> FastAPI:
    from app.routers.health import add_mission_control_cors_headers
    from app.security import verify_owner_or_api_key

    test_app = FastAPI()
    # Override security dependencies so tests don't need credentials.
    test_app.dependency_overrides[verify_owner_or_api_key] = lambda: None
    test_app.dependency_overrides[add_mission_control_cors_headers] = lambda: None
    test_app.include_router(router)
    return test_app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(_make_app())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_subscribe_returns_subscribed_state(client: TestClient) -> None:
    resp = client.post(
        "/api/constituent/subscribe",
        json={"email": "test@example.com", "topics": ["orchid-news"], "frequency": "weekly"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == PreferenceState.SUBSCRIBED
    assert body["normalized_email"] == "test@example.com"
    # Human-approval gate must be present and indicate the email is held.
    assert body["welcome_email_communication_state"] == CommunicationState.AWAITING_APPROVAL


def test_subscribe_normalizes_email(client: TestClient) -> None:
    resp = client.post(
        "/api/constituent/subscribe",
        json={"email": "  UPPER@Example.COM  "},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["normalized_email"] == "upper@example.com"


def test_subscribe_rejects_invalid_email(client: TestClient) -> None:
    resp = client.post(
        "/api/constituent/subscribe",
        json={"email": "not-an-email"},
    )
    assert resp.status_code == 422


def test_unsubscribe_returns_unsubscribed_state(client: TestClient) -> None:
    resp = client.post(
        "/api/constituent/unsubscribe",
        json={"email": "member@example.com"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == PreferenceState.UNSUBSCRIBED
    assert body["normalized_email"] == "member@example.com"


def test_unsubscribe_rejects_invalid_email(client: TestClient) -> None:
    resp = client.post(
        "/api/constituent/unsubscribe",
        json={"email": "bad"},
    )
    assert resp.status_code == 422


def test_get_preferences_returns_200(client: TestClient) -> None:
    resp = client.get("/api/constituent/preferences", params={"email": "user@example.com"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["state"] == PreferenceState.SUBSCRIBED
    assert isinstance(body["topics"], list)
    assert body["frequency"] in ("immediate", "daily", "weekly", "monthly")


def test_get_preferences_rejects_invalid_email(client: TestClient) -> None:
    resp = client.get("/api/constituent/preferences", params={"email": "nope"})
    assert resp.status_code == 422


def test_patch_preferences_updates_topics(client: TestClient) -> None:
    resp = client.patch(
        "/api/constituent/preferences",
        params={"email": "user@example.com"},
        json={"topics": ["shows", "fundraising"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["topics"] == ["shows", "fundraising"]


def test_patch_preferences_updates_frequency(client: TestClient) -> None:
    resp = client.patch(
        "/api/constituent/preferences",
        params={"email": "user@example.com"},
        json={"frequency": "monthly"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["frequency"] == "monthly"


def test_patch_preferences_rejects_invalid_frequency(client: TestClient) -> None:
    resp = client.patch(
        "/api/constituent/preferences",
        params={"email": "user@example.com"},
        json={"frequency": "never"},
    )
    assert resp.status_code == 422


def test_newsletter_archive_returns_200_with_list(client: TestClient) -> None:
    resp = client.get("/api/constituent/newsletter/archive")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "items" in body
    assert isinstance(body["items"], list)
    assert body["offset"] == 0
    assert body["limit"] == 20


def test_newsletter_archive_pagination_params(client: TestClient) -> None:
    resp = client.get("/api/constituent/newsletter/archive", params={"offset": 0, "limit": 5})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["limit"] == 5
    assert len(body["items"]) <= 5


def test_newsletter_archive_limit_bounds(client: TestClient) -> None:
    resp = client.get("/api/constituent/newsletter/archive", params={"limit": 200})
    assert resp.status_code == 422  # limit max is 100


def test_newsletter_web_version_returns_200(client: TestClient) -> None:
    # Use the stub newsletter id from routes.py
    stub_id = "00000000-0000-0000-0000-000000000002"
    resp = client.get(f"/api/constituent/newsletter/archive/{stub_id}/web")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["newsletter_id"] == stub_id
    assert "html_body" in body
    assert "plain_text_body" in body
    assert "purpose" in body


def test_newsletter_web_version_unknown_id_returns_404(client: TestClient) -> None:
    unknown_id = "ffffffff-ffff-ffff-ffff-ffffffffffff"
    resp = client.get(f"/api/constituent/newsletter/archive/{unknown_id}/web")
    assert resp.status_code == 404


def test_main_app_registers_constituent_platform_routes() -> None:
    pytest.importorskip("psycopg", reason="app.main imports the full router set")
    from app.main import app as main_app

    paths = {route.path for route in main_app.routes}
    assert "/api/constituent/subscribe" in paths
    assert "/api/constituent/unsubscribe" in paths
    assert "/api/constituent/preferences" in paths
    assert "/api/constituent/newsletter/archive" in paths
    assert "/api/constituent/newsletter/archive/{newsletter_id}/web" in paths
