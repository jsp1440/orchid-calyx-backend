from __future__ import annotations

import copy
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import harvester_command_center as api
from app.security import verify_owner_or_api_key
from runtime.harvester_command_center import CommandError, HarvesterCommandCenter

OWNER = "harvester-owner"


class FakePlane:
    def __init__(self) -> None:
        self.harvester = {
            "harvester_id": "fixture",
            "display_name": "Fixture Harvester",
            "connector_source_id": "fixture-source",
            "operational_state": "active",
            "enabled": True,
            "schedule": "daily",
            "checkpoint_cursor": "cursor-10",
            "next_scheduled_run": "2026-08-09T00:00:00Z",
            "last_attempted_run": "2026-08-08T00:00:00Z",
            "last_successful_run": "2026-08-08T00:01:00Z",
            "rows_examined": 100,
            "rows_inserted": 20,
            "warnings": ["fixture warning"],
            "errors": [],
            "current_recommendation": "continue_unchanged",
            "recommendation_rationale": "fixture telemetry",
        }
        self.runs = [{"run_id": "run-1", "status": "success", "ended_at": "2026-08-08T00:01:00Z"}]
        self.calls: list[tuple[str, str]] = []

    def list_harvesters(self) -> list[dict[str, Any]]:
        return [copy.deepcopy(self.harvester)]

    def get_harvester(self, harvester_id: str) -> dict[str, Any]:
        if harvester_id != "fixture":
            raise KeyError(harvester_id)
        return copy.deepcopy(self.harvester)

    def get_runs(self, harvester_id: str) -> list[dict[str, Any]]:
        if harvester_id != "fixture":
            raise KeyError(harvester_id)
        return copy.deepcopy(self.runs)

    def run_once(self, harvester_id: str, actor: str, execute: bool = False) -> dict[str, Any]:
        assert execute is False
        self.calls.append(("run_once", actor))
        self.runs.insert(0, {"run_id": "queued-1", "status": "queued", "ended_at": None})
        return {"status": "queued", "harvester": self.get_harvester(harvester_id)}

    def pause(self, harvester_id: str, actor: str) -> dict[str, Any]:
        self.calls.append(("pause", actor))
        self.harvester["operational_state"] = "paused"
        return {"status": "paused", "harvester": self.get_harvester(harvester_id)}

    def resume(self, harvester_id: str, actor: str) -> dict[str, Any]:
        self.calls.append(("resume", actor))
        self.harvester["operational_state"] = "active"
        return {"status": "active", "harvester": self.get_harvester(harvester_id)}

    def cancel_run(self, harvester_id: str, actor: str) -> dict[str, Any]:
        self.calls.append(("cancel", actor))
        return {"status": "no_active_run", "harvester": self.get_harvester(harvester_id)}

    def reschedule(self, harvester_id: str, schedule: str, actor: str) -> dict[str, Any]:
        self.calls.append(("reschedule", actor))
        self.harvester["schedule"] = schedule
        return {"status": "rescheduled", "harvester": self.get_harvester(harvester_id)}

    def retire(self, harvester_id: str, actor: str) -> dict[str, Any]:
        self.calls.append(("retire", actor))
        self.harvester["operational_state"] = "retired"
        return {"status": "retired", "harvester": self.get_harvester(harvester_id)}

    def restore(self, harvester_id: str, actor: str) -> dict[str, Any]:
        self.calls.append(("restore", actor))
        self.harvester["operational_state"] = "active"
        return {"status": "active", "harvester": self.get_harvester(harvester_id)}

    def reassess(self, harvester_id: str) -> dict[str, Any]:
        self.calls.append(("reassess", "system"))
        self.harvester["current_recommendation"] = "continue_unchanged"
        return {"status": "assessed", "harvester": self.get_harvester(harvester_id)}


def test_live_state_projection_is_ipad_safe_and_excludes_secret_fields():
    plane = FakePlane()
    plane.harvester["api_key"] = "must-not-leak"
    payload = HarvesterCommandCenter(plane).list_state()
    assert payload["display_contract"] == "ipad_safe_v1"
    card = payload["data"]["harvesters"][0]
    assert card["checkpoint"] == "cursor-10"
    assert card["progress"]["yield_rate"] == 0.2
    assert card["last_success"] == "2026-08-08T00:01:00Z"
    assert card["warnings"] == ["fixture warning"]
    assert "must-not-leak" not in str(card)
    assert "api_key" not in card


def test_preview_is_provably_no_write_and_never_invokes_provider_or_action():
    plane = FakePlane()
    service = HarvesterCommandCenter(plane)
    before_harvester = copy.deepcopy(plane.harvester)
    before_runs = copy.deepcopy(plane.runs)
    preview = service.preview("fixture", "run_once")
    assert preview["data"]["no_write_proof"] == {
        "verified": True,
        "state_unchanged": True,
        "run_history_unchanged": True,
    }
    assert preview["data"]["proposed_effect"]["provider_execution"] is False
    assert plane.harvester == before_harvester
    assert plane.runs == before_runs
    assert plane.calls == []


def test_low_risk_command_requires_confirmation_then_transitions_state():
    plane = FakePlane()
    service = HarvesterCommandCenter(plane)
    try:
        service.execute("fixture", "pause", OWNER, confirmed=False)
    except CommandError as exc:
        assert exc.code == "CONFIRMATION_REQUIRED"
    else:
        raise AssertionError("unconfirmed pause must fail")
    result = service.execute("fixture", "pause", OWNER, confirmed=True)
    assert result["data"]["result"]["status"] == "paused"
    assert plane.harvester["operational_state"] == "paused"
    assert plane.calls[-1] == ("pause", OWNER)


def test_high_risk_reschedule_requires_exact_phrase():
    plane = FakePlane()
    service = HarvesterCommandCenter(plane)
    try:
        service.execute("fixture", "reschedule", OWNER, confirmed=True, schedule="weekly")
    except CommandError as exc:
        assert exc.code == "CONFIRMATION_PHRASE_REQUIRED"
    else:
        raise AssertionError("high-risk reschedule must require phrase")
    result = service.execute(
        "fixture",
        "reschedule",
        OWNER,
        confirmed=True,
        confirmation_phrase="CONFIRM RESCHEDULE",
        schedule="weekly",
    )
    assert result["data"]["result"]["status"] == "rescheduled"
    assert plane.harvester["schedule"] == "weekly"


def test_run_once_is_queue_only_and_does_not_execute_provider():
    plane = FakePlane()
    result = HarvesterCommandCenter(plane).execute("fixture", "run_once", OWNER, confirmed=True)
    assert result["data"]["result"]["status"] == "queued"
    assert result["data"]["production_provider_scrape_performed"] is False
    assert plane.runs[0]["status"] == "queued"


def test_readiness_contract_preserves_governance():
    ready = HarvesterCommandCenter(FakePlane()).readiness()["data"]
    assert ready["preview_no_write_enforced"] is True
    assert ready["authorization_required"] is True
    assert ready["secrets_exposed"] is False
    assert ready["provider_scraping_from_command_center"] is False
    assert ready["production_deployment_authorized"] is False
    assert ready["production_data_test_mutation_authorized"] is False


def test_protected_api_and_stable_confirmation_error(monkeypatch):
    service = HarvesterCommandCenter(FakePlane())
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)
    state = client.get("/brain/mission-control/harvesters")
    assert state.status_code == 200
    denied = client.post("/brain/mission-control/harvesters/fixture/commands", json={"action": "pause", "confirmed": False})
    assert denied.status_code == 409
    assert denied.json()["detail"]["code"] == "CONFIRMATION_REQUIRED"
    preview = client.post("/brain/mission-control/harvesters/fixture/preview", json={"action": "pause"})
    assert preview.status_code == 200
    assert preview.json()["data"]["no_write_proof"]["verified"] is True
