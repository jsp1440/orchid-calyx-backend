"""Tests for app.kalix.routes — KALIX-BUILD-003.

Verifies GET /api/kalix/status and POST /api/kalix/speak:
  1. Auth required on both endpoints
  2. Status endpoint returns persona metadata
  3. Speak endpoint returns answer + kalix_context
  4. Governance fields are present in speak response
  5. Depth level is applied correctly
  6. Missing auth returns 401 or 403
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.kalix.routes import router
from app.security import verify_owner_or_api_key

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api")
    return application


@pytest.fixture()
def authed_client(app: FastAPI) -> TestClient:
    """TestClient with auth dependency overridden to return a valid subject."""
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "subject": "test-owner@fcos.org",
        "auth_type": "api_key",
    }
    return TestClient(app)


@pytest.fixture()
def unauthed_client(app: FastAPI) -> TestClient:
    """TestClient with auth dependency raising 401."""
    from fastapi import HTTPException

    def _deny() -> None:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED"})

    app.dependency_overrides[verify_owner_or_api_key] = _deny
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch configured_runtime_provider to return a deterministic mock."""
    provider = MagicMock()
    reply = MagicMock()
    reply.text = "Kalix deterministic reply."
    reply.provider = "deterministic"
    reply.model = "governed"
    reply.request_hash = "abc123"
    reply.provider_response_id = None
    reply.synthesis_structure = {}
    provider.generate.return_value = reply
    monkeypatch.setattr(
        "app.kalix.routes.configured_runtime_provider",
        lambda: provider,
    )
    return provider


# ── GET /api/kalix/status ─────────────────────────────────────────────────────

def test_status_requires_auth(unauthed_client: TestClient) -> None:
    r = unauthed_client.get("/api/kalix/status")
    assert r.status_code in (401, 403)


def test_status_returns_200(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.get("/api/kalix/status")
    assert r.status_code == 200


def test_status_contains_persona_version(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.get("/api/kalix/status")
    body = r.json()
    assert body["persona_version"] == "KALIX-PERSONA-001"


def test_status_contains_domain_count(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.get("/api/kalix/status")
    body = r.json()
    assert body["domain_count"] >= 10


def test_status_contains_depth_levels(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.get("/api/kalix/status")
    body = r.json()
    assert "grower" in body["depth_levels"]
    assert "researcher" in body["depth_levels"]


def test_status_governance_fields(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.get("/api/kalix/status")
    body = r.json()
    assert body["canonical_graph_mutated"] is False
    assert body["engineering_dispatch_authorized"] is False
    assert body["provider_calls"] == 0


# ── POST /api/kalix/speak ─────────────────────────────────────────────────────

def test_speak_requires_auth(unauthed_client: TestClient, mock_provider: MagicMock) -> None:
    r = unauthed_client.post("/api/kalix/speak", json={"message": "Hello Kalix"})
    assert r.status_code in (401, 403)


def test_speak_returns_200(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": "Tell me about Dendrobium"})
    assert r.status_code == 200


def test_speak_contains_answer(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": "Dendrobium care"})
    body = r.json()
    assert "answer" in body
    assert body["answer"] == "Kalix deterministic reply."


def test_speak_contains_kalix_context(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": "Orchid roots"})
    body = r.json()
    assert "kalix_context" in body
    assert "kalix_persona_context" in body["kalix_context"]


def test_speak_contains_persona_version(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": "Hello"})
    body = r.json()
    assert body["persona_version"] == "KALIX-PERSONA-001"


def test_speak_governance_fields_in_response(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": "Orchid taxonomy"})
    body = r.json()
    assert body["canonical_graph_mutated"] is False
    assert body["engineering_dispatch_authorized"] is False
    assert body["provider_calls"] == 0


def test_speak_depth_hint_applied(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Orchid metabolism", "depth_hint": "I am a botanist"},
    )
    body = r.json()
    assert body["depth_level"] == "scientist"


def test_speak_empty_message_rejected(authed_client: TestClient, mock_provider: MagicMock) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": ""})
    assert r.status_code == 422
