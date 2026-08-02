from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.live_mission_control import register_live_mission_control
from runtime.governed_worker_loop import GovernedWorkerLoop
from runtime.json_activation_store import JsonActivationStateStore
from runtime.persistent_activation_state import PersistentActivationController
from runtime.runtime_operator_controls import RuntimeOperatorControls


def require_owner() -> None:
    raise HTTPException(status_code=401, detail="owner required")


def controls(tmp_path: Path) -> RuntimeOperatorControls:
    controller = PersistentActivationController(
        JsonActivationStateStore(tmp_path / "activation.json")
    )
    worker = GovernedWorkerLoop(controller, lambda: "test-cycle")
    return RuntimeOperatorControls(controller, worker)


def test_live_registration_exposes_chat_and_fail_closed_runtime(tmp_path: Path):
    app = FastAPI()
    instance = controls(tmp_path)
    register_live_mission_control(
        app,
        require_owner=require_owner,
        get_controls=lambda: instance,
    )
    client = TestClient(app)

    assert client.get("/brain/mission-control/chat/status").status_code == 200
    status = client.get("/brain/mission-control/runtime/status")
    assert status.status_code == 200
    activation = status.json()["activation"]
    assert activation["authorized"] is False
    assert activation["paused"] is True

    assert client.post(
        "/brain/mission-control/runtime/resume",
        json={"owner_approved": True},
    ).status_code == 401


def test_live_registration_is_idempotent(tmp_path: Path):
    app = FastAPI()
    instance = controls(tmp_path)
    kwargs = {
        "require_owner": require_owner,
        "get_controls": lambda: instance,
    }
    register_live_mission_control(app, **kwargs)
    register_live_mission_control(app, **kwargs)

    client = TestClient(app)
    assert client.get("/brain/mission-control/chat/status").status_code == 200
    assert client.get("/brain/mission-control/runtime/status").status_code == 200


def test_json_store_round_trip(tmp_path: Path):
    store = JsonActivationStateStore(tmp_path / "state.json")
    assert store.load() is None
    store.save({"enabled": False, "paused": True})
    assert store.load() == {"enabled": False, "paused": True}
