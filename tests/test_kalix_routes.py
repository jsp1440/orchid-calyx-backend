"""Tests for app.kalix.routes — KALIX-BUILD-003."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.kalix.routes import router
from app.security import verify_owner_or_api_key


@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router, prefix="/api")
    return application


@pytest.fixture()
def authed_client(app: FastAPI) -> TestClient:
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {
        "subject": "test-owner@fcos.org",
        "auth_type": "api_key",
    }
    return TestClient(app)


@pytest.fixture()
def unauthed_client(app: FastAPI) -> TestClient:
    from fastapi import HTTPException

    def _deny() -> None:
        raise HTTPException(401, detail={"code": "UNAUTHORIZED"})

    app.dependency_overrides[verify_owner_or_api_key] = _deny
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture()
def mock_provider(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    provider = MagicMock()
    provider.provider_name = "deterministic"
    provider.model_name = "governed"
    reply = MagicMock()
    reply.text = "Kalix deterministic reply."
    reply.provider = "deterministic"
    reply.model = "governed"
    provider.generate.return_value = reply
    monkeypatch.setattr("app.kalix.routes.configured_runtime_provider", lambda: provider)
    return provider


def test_status_requires_auth(unauthed_client: TestClient) -> None:
    r = unauthed_client.get("/api/kalix/status")
    assert r.status_code in (401, 403)


def test_status_returns_persona_metadata(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    body = authed_client.get("/api/kalix/status").json()
    assert body["persona"] == "Kalix"
    assert body["persona_version"] == "KALIX-PERSONA-001"
    assert body["domain_count"] >= 10
    assert "grower" in body["depth_levels"]
    assert "researcher" in body["depth_levels"]
    assert body["canonical_graph_mutated"] is False
    assert body["engineering_dispatch_authorized"] is False
    assert body["provider_calls"] == 0


def test_speak_requires_auth(unauthed_client: TestClient, mock_provider: MagicMock) -> None:
    r = unauthed_client.post("/api/kalix/speak", json={"message": "Hello Kalix"})
    assert r.status_code in (401, 403)


def test_speak_returns_acceptance_contract(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    body = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Tell me about Dendrobium"},
    ).json()
    assert body["persona"] == "Kalix"
    assert body["answer"] == "Kalix deterministic reply."
    assert body["knowledge"] == body["kalix_context"]
    assert "kalix_persona_context" in body["knowledge"]
    assert body["depth_used"] == "grower"
    assert body["provider_calls"] == 0


def test_speak_explicit_depth_wins_over_hint(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    body = authed_client.post(
        "/api/kalix/speak",
        json={
            "message": "Orchid metabolism",
            "depth": "researcher",
            "depth_hint": "I am a student",
        },
    ).json()
    assert body["depth_used"] == "researcher"


def test_speak_depth_hint_adapts_when_explicit_depth_absent(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    body = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Orchid metabolism", "depth_hint": "I am a botanist"},
    ).json()
    assert body["depth_used"] == "scientist"


def test_speak_project_id_is_preserved_in_context(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    body = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Review this project", "project_id": "research-station-42"},
    ).json()
    assert body["project_id"] == "research-station-42"
    assert (
        body["knowledge"]["kalix_persona_context"]["persona_config"]["project_id"]
        == "research-station-42"
    )


def test_speak_rejects_invalid_depth(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    r = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Hello", "depth": "expert"},
    )
    assert r.status_code == 422


def test_speak_empty_message_rejected(
    authed_client: TestClient, mock_provider: MagicMock
) -> None:
    r = authed_client.post("/api/kalix/speak", json={"message": ""})
    assert r.status_code == 422


def test_generative_provider_call_is_counted(
    authed_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    provider.provider_name = "openai"
    provider.model_name = "test-model"
    reply = MagicMock()
    reply.text = "provider reply"
    reply.provider = "openai"
    reply.model = "test-model"
    provider.generate.return_value = reply
    monkeypatch.setattr("app.kalix.routes.configured_runtime_provider", lambda: provider)

    body = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Hello"},
    ).json()
    assert body["provider_calls"] == 1


def test_primary_provider_failure_falls_back_and_preserves_call_count(
    authed_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = MagicMock()
    provider.provider_name = "openai"
    provider.model_name = "test-model"
    provider.generate.side_effect = RuntimeError("provider unavailable")
    monkeypatch.setattr("app.kalix.routes.configured_runtime_provider", lambda: provider)

    body = authed_client.post(
        "/api/kalix/speak",
        json={"message": "Hello"},
    ).json()
    assert body["provider_calls"] == 1
    assert body["provider"]["fallback_error"] is not None
