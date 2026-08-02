from fastapi.testclient import TestClient

from app.main import app
from app.routers.calyx_operator_chat import reset_chat_for_tests


def test_live_chat_and_runtime_status_are_registered_fail_closed():
    reset_chat_for_tests()
    client = TestClient(app)

    chat = client.get("/brain/mission-control/chat/status")
    assert chat.status_code == 200
    assert chat.json()["auditable"] is True

    runtime = client.get("/brain/mission-control/runtime/status")
    assert runtime.status_code == 200
    activation = runtime.json()["activation"]
    assert activation["enabled"] is False
    assert activation["owner_approved"] is False
    assert activation["paused"] is True
    assert activation["authorized"] is False


def test_runtime_mutation_rejects_unauthenticated_requests():
    client = TestClient(app)
    response = client.post(
        "/brain/mission-control/runtime/run-once",
        json={"owner_approved": True},
    )
    assert response.status_code in {401, 403, 503}
