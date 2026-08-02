from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.routers.calyx_runtime_controls import create_runtime_controls_router


class FakeControls:
    def status(self):
        return {
            "activation": {"authorized": False},
            "safety": {"automatic_merge": False},
        }

    def pause(self, *, owner_approved):
        return {"paused": True, "owner_approved": owner_approved}

    def resume(self, *, owner_approved):
        return {"paused": False, "owner_approved": owner_approved}

    def run_once(self, *, owner_approved):
        return {"executed": owner_approved}

    def configure(self, *, owner_approved, interval_minutes, max_draft_prs_per_cycle):
        return {
            "owner_approved": owner_approved,
            "interval_minutes": interval_minutes,
            "max_draft_prs_per_cycle": max_draft_prs_per_cycle,
        }


def build_client(*, authorized: bool) -> TestClient:
    app = FastAPI()

    def require_owner():
        if not authorized:
            raise HTTPException(status_code=401, detail="owner authorization required")

    app.include_router(
        create_runtime_controls_router(lambda: FakeControls(), require_owner)
    )
    return TestClient(app)


def test_status_is_read_only():
    response = build_client(authorized=False).get(
        "/brain/mission-control/runtime/status"
    )
    assert response.status_code == 200
    assert response.json()["safety"]["automatic_merge"] is False


def test_runtime_mutations_require_owner_authentication():
    response = build_client(authorized=False).post(
        "/brain/mission-control/runtime/resume",
        json={"owner_approved": True},
    )
    assert response.status_code == 401


def test_owner_can_resume_and_run_once():
    client = build_client(authorized=True)
    resumed = client.post(
        "/brain/mission-control/runtime/resume",
        json={"owner_approved": True},
    )
    assert resumed.status_code == 200
    assert resumed.json()["paused"] is False

    run = client.post(
        "/brain/mission-control/runtime/run-once",
        json={"owner_approved": True},
    )
    assert run.status_code == 200
    assert run.json()["executed"] is True


def test_configuration_is_bounded():
    response = build_client(authorized=True).post(
        "/brain/mission-control/runtime/configure",
        json={
            "owner_approved": True,
            "interval_minutes": 1,
            "max_draft_prs_per_cycle": 1,
        },
    )
    assert response.status_code == 422
