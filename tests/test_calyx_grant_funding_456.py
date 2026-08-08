from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import grant_funding as api
from app.security import verify_owner_or_api_key
from runtime.grant_funding import GrantFundingService

OWNER = "funding-owner"


def profile() -> dict[str, Any]:
    return {
        "profile_id": "orchid-continuum",
        "organization": "Five Cities Orchid Society",
        "organization_type": "501c3",
        "jurisdiction": "US-CA",
        "mission": "Orchid education and conservation",
        "project_name": "Orchid Continuum",
        "project_summary": "Biodiversity intelligence and conservation infrastructure.",
        "focus_areas": ["biodiversity", "conservation", "education"],
        "geographies": ["United States", "California"],
        "eligible_entity_types": ["nonprofit"],
        "requested_currency": "USD",
        "requested_amount": 50000,
    }


def opportunity() -> dict[str, Any]:
    return {
        "opportunity_id": "fixture-grant",
        "funder": "Fixture Foundation",
        "title": "Biodiversity Infrastructure Grant",
        "description": "Supports biodiversity and conservation projects.",
        "source_url": "https://example.org/grants/fixture",
        "retrieved_at": "2026-08-08T06:00:00Z",
        "jurisdiction": "US",
        "currency": "USD",
        "amount_min": 10000,
        "amount_max": 100000,
        "deadline": "2026-10-01",
        "deadline_confidence": 1.0,
        "eligibility": {"entity_types": ["nonprofit"]},
        "requirements": [{"name": "narrative"}, {"name": "budget"}],
        "focus_areas": ["biodiversity", "conservation"],
        "geographies": ["United States"],
        "contact": {"name": "Program Office", "email": "grants@example.org"},
        "provenance": {"source_url": "https://example.org/grants/fixture", "retrieved_at": "2026-08-08T06:00:00Z"},
    }


def service(tmp_path: Path) -> GrantFundingService:
    return GrantFundingService(tmp_path / "funding")


def seed(svc: GrantFundingService) -> None:
    svc.save_profile(OWNER, profile())
    svc.record_opportunity(OWNER, opportunity())


def test_source_provenance_and_deadline_confidence_are_preserved(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    stored = svc.get_opportunity(OWNER, "fixture-grant")
    assert stored["source_url"] == "https://example.org/grants/fixture"
    assert stored["retrieved_at"] == "2026-08-08T06:00:00Z"
    assert stored["deadline"] == "2026-10-01"
    assert stored["deadline_confidence"] == 1.0
    assert stored["submission_performed"] is False
    assert stored["outreach_performed"] is False


def test_fit_scoring_is_deterministic_and_explained(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    first = svc.assess_fit(OWNER, "orchid-continuum", "fixture-grant")
    second = svc.assess_fit(OWNER, "orchid-continuum", "fixture-grant")
    assert first["score"] == 100
    assert first["status"] == "strong_fit"
    assert first["missing_information"] == []
    assert first["eligibility_state"] == "supported"
    assert first["score"] == second["score"]
    assert first["explanation"] == second["explanation"]


def test_missing_eligibility_never_becomes_fabricated_eligibility(tmp_path: Path):
    svc = service(tmp_path)
    svc.save_profile(OWNER, profile())
    item = opportunity()
    item["eligibility"] = {}
    svc.record_opportunity(OWNER, item)
    result = svc.assess_fit(OWNER, "orchid-continuum", "fixture-grant")
    assert result["eligibility_state"] == "unknown"
    assert "opportunity.eligibility.entity_types" in result["missing_information"]
    assert result["status"] == "needs_information"


def test_sensitive_profile_fields_fail_closed(tmp_path: Path):
    svc = service(tmp_path)
    item = profile()
    item["api_key"] = "must-not-store"
    try:
        svc.save_profile(OWNER, item)
    except ValueError as exc:
        assert str(exc).startswith("FUNDING_SENSITIVE_FIELD_REJECTED")
    else:
        raise AssertionError("sensitive funding profile data must be rejected")


def test_draft_is_review_only_artifact_and_never_submission_authority(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    draft = svc.create_draft(OWNER, "orchid-continuum", "fixture-grant")
    assert draft["human_review_required"] is True
    assert draft["submission_authorized"] is False
    assert draft["outreach_authorized"] is False
    assert draft["artifact"]["source_uri"] == "https://example.org/grants/fixture"
    assert "DRAFT FOR HUMAN REVIEW" in draft["narrative"]
    assert draft["budget_outline"]["requested_amount"] == 50000


def test_repeated_draft_generation_is_content_stable_and_registry_safe(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    first = svc.create_draft(OWNER, "orchid-continuum", "fixture-grant")
    second = svc.create_draft(OWNER, "orchid-continuum", "fixture-grant")
    assert first["artifact"]["artifact_id"] == second["artifact"]["artifact_id"]
    assert first["artifact"]["checksum"] == second["artifact"]["checksum"]
    assert first["narrative"] == second["narrative"]


def test_readiness_preserves_governance_boundaries(tmp_path: Path):
    svc = service(tmp_path)
    seed(svc)
    ready = svc.readiness(OWNER, "orchid-continuum", "fixture-grant")
    assert ready["decision"] == "REVIEW_READY"
    assert ready["human_review_required"] is True
    assert ready["eligibility_fabrication_authorized"] is False
    assert ready["grant_submission_authorized"] is False
    assert ready["autonomous_outreach_authorized"] is False
    assert ready["binding_commitment_authorized"] is False
    assert ready["secret_storage_authorized"] is False
    assert ready["production_deployment_authorized"] is False


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    saved_profile = client.put("/brain/mission-control/funding/profiles/orchid-continuum", json=profile())
    assert saved_profile.status_code == 200
    saved_opportunity = client.put("/brain/mission-control/funding/opportunities/fixture-grant", json=opportunity())
    assert saved_opportunity.status_code == 200
    assessed = client.post("/brain/mission-control/funding/profiles/orchid-continuum/opportunities/fixture-grant/assess")
    assert assessed.status_code == 200
    assert assessed.json()["score"] == 100
    drafted = client.post("/brain/mission-control/funding/profiles/orchid-continuum/opportunities/fixture-grant/draft")
    assert drafted.status_code == 200
    assert drafted.json()["submission_authorized"] is False
    readiness = client.get("/brain/mission-control/funding/profiles/orchid-continuum/opportunities/fixture-grant/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["decision"] == "REVIEW_READY"
