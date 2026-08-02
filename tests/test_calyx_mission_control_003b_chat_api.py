from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.calyx_operator_chat import reset_chat_for_tests, router


def client() -> TestClient:
    reset_chat_for_tests()
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_operator_message_and_transcript_round_trip():
    active = client()
    response = active.post(
        "/brain/mission-control/chat/messages",
        json={"content": "What are you working on?"},
    )
    assert response.status_code == 200
    transcript = active.get("/brain/mission-control/chat/transcript").json()
    assert transcript["messages"][0]["role"] == "operator"


def test_action_reply_is_marked_for_approval():
    active = client()
    response = active.post(
        "/brain/mission-control/chat/replies",
        json={
            "content": "I prepared a draft pull request.",
            "proposed_action": "create-draft-pr",
        },
    )
    assert response.status_code == 200
    assert response.json()["requires_approval"] is True


def test_status_proves_consequential_actions_are_disabled():
    status = client().get("/brain/mission-control/chat/status").json()
    assert status["automatic_merge"] is False
    assert status["automatic_deploy"] is False
    assert status["automatic_publication"] is False
    assert status["external_communication"] is False


def test_empty_operator_message_is_rejected():
    response = client().post(
        "/brain/mission-control/chat/messages",
        json={"content": ""},
    )
    assert response.status_code == 422
