from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import ecological_interactions as api
from app.security import verify_owner_or_api_key
from runtime.ecological_interactions import EcologicalInteractionService

OWNER = "interaction-owner"


def subject() -> dict[str, str]:
    return {"taxon_id": "orchid-1", "scientific_name": "Cattleya labiata"}


def pollinator() -> dict[str, str]:
    return {"taxon_id": "bee-1", "scientific_name": "Eulaema meriana"}


def evidence() -> dict[str, str]:
    return {
        "evidence_id": "ev-1",
        "source_id": "doi:10.example/fixture",
        "source_url": "https://example.org/paper",
        "exact_text": "A documented floral visitor transferred pollinia between flowers.",
        "locator": "p. 4, paragraph 2",
        "retrieved_at": "2026-08-08T06:00:00Z",
    }


def documented_pollination() -> dict[str, Any]:
    return {
        "interaction_id": "int-1",
        "subject_taxon": subject(),
        "interaction_type": "pollinates",
        "organism_identity": "Eulaema meriana",
        "organism_taxon_candidates": [pollinator()],
        "locality": "Brazil",
        "observed_at": "2024-01-01",
        "evidence": evidence(),
        "confidence": 0.92,
        "contradiction": False,
        "pollination_documented": True,
    }


def service(tmp_path: Path) -> EcologicalInteractionService:
    return EcologicalInteractionService(tmp_path / "interactions")


def test_documented_pollination_preserves_exact_evidence_and_canonical_keys(tmp_path: Path):
    svc = service(tmp_path)
    record = svc.record(OWNER, documented_pollination())
    assert record["review_status"] == "candidate_ready"
    assert record["subject_taxon_key"] == "id:orchid-1"
    assert record["organism_taxon_key"] == "id:bee-1"
    assert record["evidence"]["exact_text"] == evidence()["exact_text"]
    assert record["evidence"]["locator"] == "p. 4, paragraph 2"
    assert record["provenance"]["source_url"] == "https://example.org/paper"
    assert record["provenance"]["production_graph_mutation_authorized"] is False


def test_undocumented_pollination_is_rejected_instead_of_inferred(tmp_path: Path):
    svc = service(tmp_path)
    payload = documented_pollination()
    payload["pollination_documented"] = False
    try:
        svc.record(OWNER, payload)
    except ValueError as exc:
        assert str(exc) == "INTERACTION_POLLINATION_DOCUMENTATION_REQUIRED"
    else:
        raise AssertionError("undocumented pollination must fail closed")


def test_ambiguous_organism_enters_review_queue(tmp_path: Path):
    svc = service(tmp_path)
    payload = documented_pollination()
    payload["interaction_id"] = "int-ambiguous"
    payload["interaction_type"] = "visits_flower"
    payload["pollination_documented"] = False
    payload["organism_taxon_candidates"] = [
        pollinator(),
        {"taxon_id": "bee-2", "scientific_name": "Eulaema nigrita"},
    ]
    record = svc.record(OWNER, payload)
    assert record["review_status"] == "review_required"
    assert "organism_taxon_ambiguous" in record["review_reasons"]
    queue = svc.review_queue(OWNER)
    assert queue["count"] == 1
    assert queue["records"][0]["interaction_id"] == "int-ambiguous"


def test_low_confidence_and_contradiction_are_explicit_review_reasons(tmp_path: Path):
    svc = service(tmp_path)
    payload = documented_pollination()
    payload["interaction_id"] = "int-low"
    payload["interaction_type"] = "visits_flower"
    payload["pollination_documented"] = False
    payload["confidence"] = 0.5
    payload["contradiction"] = True
    record = svc.record(OWNER, payload)
    assert record["review_status"] == "review_required"
    assert record["review_reasons"] == ["contradictory_evidence", "low_confidence"]


def test_incomplete_evidence_span_fails_closed(tmp_path: Path):
    svc = service(tmp_path)
    payload = documented_pollination()
    payload["evidence"]["locator"] = ""
    try:
        svc.record(OWNER, payload)
    except ValueError as exc:
        assert str(exc) == "INTERACTION_EVIDENCE_SPAN_INCOMPLETE"
    else:
        raise AssertionError("incomplete evidence must not produce an interaction record")


def test_bounded_stage_is_idempotent_and_never_mutates_production_graph(tmp_path: Path):
    svc = service(tmp_path)
    svc.record(OWNER, documented_pollination())
    first = svc.stage(OWNER, limit=1)
    second = svc.stage(OWNER, limit=1)
    assert first["added"] == 1
    assert first["already_staged"] == 0
    assert second["added"] == 0
    assert second["already_staged"] == 1
    assert second["total_staged"] == 1
    assert first["production_graph_mutation_performed"] is False
    assert first["relationship_provenance_preserved"] is True


def test_readiness_preserves_scientific_and_production_governance(tmp_path: Path):
    svc = service(tmp_path)
    svc.record(OWNER, documented_pollination())
    ready = svc.readiness(OWNER)
    assert ready["decision"] == "REVIEW_READY"
    assert ready["candidate_ready_count"] == 1
    assert ready["literature_evidence_binding_required"] is True
    assert ready["undocumented_pollination_inference_authorized"] is False
    assert ready["scientific_publication_authorized"] is False
    assert ready["production_graph_mutation_authorized"] is False
    assert ready["production_deployment_authorized"] is False


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    saved = client.put("/brain/mission-control/interactions/int-1", json=documented_pollination())
    assert saved.status_code == 200
    assert saved.json()["review_status"] == "candidate_ready"

    fetched = client.get("/brain/mission-control/interactions/int-1")
    assert fetched.status_code == 200
    assert fetched.json()["record_digest"] == saved.json()["record_digest"]

    staged = client.post("/brain/mission-control/interactions/stage?limit=10")
    assert staged.status_code == 200
    assert staged.json()["added"] == 1

    readiness = client.get("/brain/mission-control/interactions/status/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["production_graph_mutation_authorized"] is False
