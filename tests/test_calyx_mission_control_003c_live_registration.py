import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mission_control_registration import register_mission_control_chat
from app.routers.calyx_operator_chat import reset_chat_for_tests

API_KEY = "test-api-key"


@pytest.fixture(autouse=True)
def _api_key(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", API_KEY)


def build_app() -> FastAPI:
    app = FastAPI()
    register_mission_control_chat(app)
    return app


def test_registration_exposes_chat_status_and_message_routes():
    reset_chat_for_tests()
    client = TestClient(build_app())
    status = client.get("/brain/mission-control/chat/status")
    assert status.status_code == 200
    assert status.json()["auditable"] is True

    message = client.post(
        "/brain/mission-control/chat/messages",
        json={"content": "What are you working on?"},
        headers={"X-API-Key": API_KEY},
    )
    assert message.status_code == 200
    assert message.json()["role"] == "operator"


def test_registration_is_idempotent():
    app = build_app()
    register_mission_control_chat(app)
    client = TestClient(app)
    response = client.get("/brain/mission-control/chat/status")
    assert response.status_code == 200
