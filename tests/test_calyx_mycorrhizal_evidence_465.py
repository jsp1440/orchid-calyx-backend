from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import mycorrhizal_evidence as api
from app.security import verify_owner_or_api_key
from runtime.literature_acquisition import LiteratureAcquisitionService
from runtime.mycorrhizal_evidence import MycorrhizalEvidenceService

OWNER = "mycorrhiza-owner"


def make_service(tmp_path: Path) -> tuple[MycorrhizalEvidenceService, str]:
    literature = LiteratureAcquisitionService(tmp_path / "literature")
    readiness = literature.intake_bytes(
        "fixture.txt",
        b"Root sections contained intracellular pelotons associated with a cultured Tulasnella isolate.",
        source_ref="https://example.org/mycorrhiza-paper",
    )
    service = MycorrhizalEvidenceService(tmp_path / "mycorrhiza", literature=literature)
    return service, readiness["run_id"]


def association(run_id: str) -> dict[str, Any]:
    return {
        "association_id": "assoc-1",
        "association_type": "mycorrhizal_association",
        "association_documented": True,
        "orchid_taxon": {"taxon_id": "orchid-1", "scientific_name": "Dendrobium kingianum"},
        "fungal_identity": "Tulasnella calospora",
        "fungal_candidates": [{"taxon_id": "fungus-1", "scientific_name": "Tulasnella calospora"}],
        "tissue": "root",
        "life_stage": "adult",
        "locality": "Australia",
        "method": "microscopy and fungal isolation",
        "evidence": {"literature_run_id": run_id, "span_id": 1},
        "confidence": 0.9,
        "contradiction": False,
    }


def test_exact_literature_span_is_bound_with_taxon_and_fungal_identity(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    record = service.record(OWNER, association(run_id))
    assert record["review_status"] == "candidate_ready"
    assert record["orchid_taxon_key"] == "id:orchid-1"
    assert record["fungal_taxon_key"] == "id:fungus-1"
    assert record["evidence"]["literature_run_id"] == run_id
    assert record["evidence"]["span_id"] == 1
    assert record["evidence"]["sha256"]
    assert "pelotons" in record["evidence"]["text"]


def test_verified_mycorrhizal_association_requires_documented_evidence_flag(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    payload = association(run_id)
    payload["association_documented"] = False
    try:
        service.record(OWNER, payload)
    except ValueError as exc:
        assert str(exc) == "MYCORRHIZA_ASSOCIATION_DOCUMENTATION_REQUIRED"
    else:
        raise AssertionError("undocumented association must fail closed")


def test_cooccurrence_cannot_be_promoted_to_verified_symbiosis(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    payload = association(run_id)
    payload["association_type"] = "co_occurrence_only"
    payload["association_documented"] = True
    try:
        service.record(OWNER, payload)
    except ValueError as exc:
        assert str(exc) == "MYCORRHIZA_COOCCURRENCE_CANNOT_VERIFY_SYMBIOSIS"
    else:
        raise AssertionError("co-occurrence must not become verified symbiosis")


def test_ambiguous_fungal_identity_enters_unresolved_queue(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    payload = association(run_id)
    payload["association_id"] = "assoc-ambiguous"
    payload["fungal_candidates"] = [
        {"taxon_id": "fungus-1", "scientific_name": "Tulasnella calospora"},
        {"taxon_id": "fungus-2", "scientific_name": "Tulasnella irregularis"},
    ]
    record = service.record(OWNER, payload)
    assert record["review_status"] == "review_required"
    assert "fungal_identity_ambiguous" in record["review_reasons"]
    queue = service.unresolved_queue(OWNER)
    assert queue["count"] == 1
    assert queue["records"][0]["association_id"] == "assoc-ambiguous"


def test_provenance_traverses_association_to_exact_literature_revision(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    service.record(OWNER, association(run_id))
    path = service.provenance(OWNER, "assoc-1")["path"]
    assert [item["type"] for item in path] == ["association", "literature_evidence_span", "literature_revision"]
    assert path[1]["id"] == f"{run_id}:1"
    assert path[1]["sha256"]
    assert path[2]["source_sha256"]


def test_bounded_projection_is_idempotent_and_review_only(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    service.record(OWNER, association(run_id))
    first = service.stage(OWNER, limit=1)
    second = service.stage(OWNER, limit=1)
    assert first["added"] == 1
    assert second["added"] == 0
    assert second["already_staged"] == 1
    assert second["total_staged"] == 1
    assert second["production_graph_mutation_performed"] is False
    assert second["provenance_preserved"] is True


def test_readiness_preserves_non_authority(tmp_path: Path):
    service, run_id = make_service(tmp_path)
    service.record(OWNER, association(run_id))
    readiness = service.readiness(OWNER)
    assert readiness["decision"] == "REVIEW_READY"
    assert readiness["literature_evidence_bound"] is True
    assert readiness["cooccurrence_as_verified_symbiosis_authorized"] is False
    assert readiness["scientific_publication_authorized"] is False
    assert readiness["production_graph_mutation_authorized"] is False
    assert readiness["production_deployment_authorized"] is False


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    service, run_id = make_service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    saved = client.put("/brain/mission-control/mycorrhiza/assoc-1", json=association(run_id))
    assert saved.status_code == 200
    assert saved.json()["review_status"] == "candidate_ready"

    provenance = client.get("/brain/mission-control/mycorrhiza/assoc-1/provenance")
    assert provenance.status_code == 200
    assert provenance.json()["path"][1]["type"] == "literature_evidence_span"

    staged = client.post("/brain/mission-control/mycorrhiza/stage?limit=10")
    assert staged.status_code == 200
    assert staged.json()["added"] == 1

    readiness = client.get("/brain/mission-control/mycorrhiza/status/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["production_graph_mutation_authorized"] is False
