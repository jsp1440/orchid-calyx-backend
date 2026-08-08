from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import conservation_evidence as api
from app.security import verify_owner_or_api_key
from runtime.conservation_evidence import ConservationEvidenceService
from runtime.literature_acquisition import LiteratureAcquisitionService

OWNER = "conservation-owner"


def make_service(tmp_path: Path) -> tuple[ConservationEvidenceService, str]:
    literature = LiteratureAcquisitionService(tmp_path / "literature")
    readiness = literature.intake_bytes(
        "fixture.txt",
        b"The cited assessment records the taxon as Endangered and identifies habitat loss as a documented threat.",
        source_ref="https://example.org/conservation-assessment",
    )
    service = ConservationEvidenceService(
        tmp_path / "conservation",
        literature=literature,
        as_of=date(2026, 8, 8),
        stale_after_years=5,
    )
    return service, readiness["run_id"]


def assessment(run_id: str) -> dict[str, Any]:
    return {
        "assessment_id": "assessment-1",
        "taxon": {"taxon_id": "orchid-1", "scientific_name": "Paphiopedilum rothschildianum"},
        "source_authority": "IUCN",
        "assessment_version": "2024.1",
        "assessment_date": "2024-06-01",
        "category_system": "IUCN Red List",
        "category": "Endangered",
        "population": {"estimate": None, "basis": "source did not provide numeric population in fixture"},
        "trend": "decreasing",
        "threats": [{"type": "habitat loss", "documented": True}],
        "protected_areas": [{"name": "Fixture Reserve", "atlas_feature_id": "atlas-pa-1"}],
        "actions": [{"type": "habitat protection", "source_stated": True}],
        "evidence": {"literature_run_id": run_id, "span_id": 1},
        "confidence": 0.9,
        "conflicts": [],
        "occurrence_evidence_ids": ["occ-1"],
        "atlas_feature_ids": ["atlas-pa-1"],
    }


def test_current_assessment_preserves_authority_status_evidence_and_links(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    record = service.record(OWNER, assessment(run_id))
    assert record["review_status"] == "candidate_ready"
    assert record["taxon_key"] == "id:orchid-1"
    assert record["source_authority"] == "IUCN"
    assert record["category"] == "Endangered"
    assert record["freshness"]["state"] == "current"
    assert record["evidence"]["literature_run_id"] == run_id
    assert record["evidence"]["sha256"]
    assert record["occurrence_evidence_ids"] == ["occ-1"]
    assert record["atlas_feature_ids"] == ["atlas-pa-1"]


def test_iucn_category_requires_iucn_source_authority(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    payload = assessment(run_id)
    payload["source_authority"] = "Unverified Blog"
    try:
        service.record(OWNER, payload)
    except ValueError as exc:
        assert str(exc) == "CONSERVATION_IUCN_AUTHORITY_REQUIRED"
    else:
        raise AssertionError("IUCN status must fail closed without IUCN authority")


def test_stale_assessment_is_detected_and_enters_review(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    payload = assessment(run_id)
    payload["assessment_id"] = "assessment-stale"
    payload["assessment_date"] = "2015-01-01"
    record = service.record(OWNER, payload)
    assert record["freshness"]["state"] == "stale"
    assert record["review_status"] == "review_required"
    assert "stale_assessment" in record["review_reasons"]
    assert service.review_queue(OWNER)["count"] == 1


def test_conflicts_and_low_confidence_are_explicit_review_reasons(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    payload = assessment(run_id)
    payload["assessment_id"] = "assessment-conflict"
    payload["confidence"] = 0.5
    payload["conflicts"] = [{"source": "older assessment", "category": "Vulnerable"}]
    record = service.record(OWNER, payload)
    assert record["review_status"] == "review_required"
    assert record["review_reasons"] == ["conflicting_assessments_or_evidence", "low_confidence"]


def test_bounded_staging_is_idempotent_and_non_publishing(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    service.record(OWNER, assessment(run_id))
    first = service.stage(OWNER, limit=1)
    second = service.stage(OWNER, limit=1)
    assert first["added"] == 1
    assert second["added"] == 0
    assert second["already_staged"] == 1
    assert second["total_staged"] == 1
    assert second["production_graph_mutation_performed"] is False
    assert second["scientific_publication_performed"] is False


def test_readiness_reports_stale_and_governance_state(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    service.record(OWNER, assessment(run_id))
    stale = assessment(run_id)
    stale["assessment_id"] = "assessment-stale"
    stale["assessment_date"] = "2010-01-01"
    service.record(OWNER, stale)
    ready = service.readiness(OWNER)
    assert ready["decision"] == "REVIEW_READY"
    assert ready["candidate_ready_count"] == 1
    assert ready["stale_assessment_count"] == 1
    assert ready["fabricated_iucn_status_authorized"] is False
    assert ready["scientific_publication_authorized"] is False
    assert ready["production_graph_mutation_authorized"] is False
    assert ready["production_deployment_authorized"] is False


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    service, run_id = make_service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    saved = client.put("/brain/mission-control/conservation/assessment-1", json=assessment(run_id))
    assert saved.status_code == 200
    assert saved.json()["review_status"] == "candidate_ready"

    staged = client.post("/brain/mission-control/conservation/stage?limit=10")
    assert staged.status_code == 200
    assert staged.json()["added"] == 1

    readiness = client.get("/brain/mission-control/conservation/status/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["fabricated_iucn_status_authorized"] is False
