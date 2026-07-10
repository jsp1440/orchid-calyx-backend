from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.harvesters import router
from runtime.harvester_control import HarvesterControlPlane


def test_registry_seeds_required_harvesters_idempotently():
    plane = HarvesterControlPlane()
    first = plane.list_harvesters()
    second = plane.list_harvesters()
    assert len(first) == len(second)
    ids = {item["harvester_id"] for item in first}
    assert {"inaturalist", "gbif", "image_media", "literature", "mycorrhizal_data"} <= ids
    assert all(item["rows_examined"] is None for item in first)


def test_pause_resume_and_run_once_preserve_history():
    plane = HarvesterControlPlane()
    assert plane.pause("gbif", "owner")["harvester"]["operational_state"] == "paused"
    assert plane.resume("gbif", "owner")["harvester"]["operational_state"] == "active"
    run = plane.run_once("gbif", "owner")
    assert run["run"]["status"] == "queued"
    assert plane.get_runs("gbif")[0]["run_id"] == run["run"]["run_id"]


def test_retirement_does_not_delete_history():
    plane = HarvesterControlPlane()
    plane.run_once("literature", "owner")
    result = plane.retire("literature", "owner")
    assert result["harvester"]["operational_state"] in {"retired", "needs_review"}
    assert len(plane.get_runs("literature")) == 1


def test_target_proposal_approval_and_rejection_are_recorded():
    plane = HarvesterControlPlane()
    proposal = plane.propose_target_change(
        "inaturalist",
        {"target_type": "geography", "target_value": "Ecuador"},
        "Ecuador orchid occurrence freshness has high knowledge-gap relevance.",
    )["proposal"]
    approved = plane.approve_proposal("inaturalist", proposal["proposal_id"], "owner")
    assert approved["status"] in {"approved", "review_required"}
    proposal_2 = plane.propose_target_change("gbif", {"target_type": "date_range", "target_value": "2025-2026"}, "freshness check")
    rejected = plane.reject_proposal("gbif", proposal_2["proposal"]["proposal_id"], "owner")
    assert rejected["proposal"]["status"] == "rejected"


def test_high_risk_review_enforced_by_policy():
    plane = HarvesterControlPlane()
    result = plane.update_schedule("gbif", "hourly", "owner")
    assert result["status"] in {"updated", "review_required"}
    if result["status"] == "review_required":
        assert result["decision"]["risk_level"] == "high"


def test_duplicate_heavy_recommendation_reduces_frequency():
    plane = HarvesterControlPlane()
    harvester = plane._require_harvester("gbif")
    harvester.rows_examined = 100
    harvester.rows_inserted = 2
    harvester.duplicates_detected = 85
    recommendation = plane.recommendation("gbif")
    assert recommendation["recommendation"] == "reduce_frequency"


def test_exhausted_source_detection():
    plane = HarvesterControlPlane()
    harvester = plane._require_harvester("literature")
    harvester.rows_examined = 100
    harvester.rows_inserted = 0
    harvester.duplicates_detected = 90
    harvester.source_exhaustion_score = 0.9
    recommendation = plane.recommendation("literature")
    assert recommendation["recommendation"] == "retire_as_exhausted"
    assert recommendation["approval_requirement"] == "owner_review"


def test_api_routes_and_credential_non_disclosure(monkeypatch):
    monkeypatch.setenv("CALYX_API_KEY", "test-secret")
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)
    listed = client.get("/api/harvesters")
    assert listed.status_code == 200
    assert "test-secret" not in listed.text
    unauthorized = client.post("/api/harvesters/gbif/pause")
    assert unauthorized.status_code == 401
    authorized = client.post("/api/harvesters/gbif/pause", headers={"X-API-Key": "test-secret"})
    assert authorized.status_code == 200
