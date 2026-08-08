from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import species_dossier as api
from app.security import verify_owner_or_api_key
from runtime.species_dossier import DOMAIN_NAMES, SpeciesDossierService

OWNER = "dossier-owner"


def payload() -> dict[str, Any]:
    return {
        "stable_taxon_id": "hassler:12345",
        "identity": {
            "scientific_name": "Cattleya skinneri",
            "rank": "species",
            "authorship": "Bateman",
            "aliases": ["Guarianthe skinneri"],
        },
        "domains": {
            "nomenclature": {
                "state": "available",
                "items": [{"accepted_name": "Cattleya skinneri"}],
                "provenance": [{"source": "reviewed-taxonomy", "release_id": "fixture"}],
            },
            "media": {
                "state": "partial",
                "items": [{"media_id": "m-1"}],
                "provenance": [{"source": "licensed-media", "record_id": "m-1"}],
            },
            "pollination": {
                "state": "review_required",
                "items": [{"interaction_id": "i-1"}],
                "provenance": [{"source": "ecological-interactions", "record_id": "i-1"}],
                "contradictions": [{"claim": "pollinator identity differs across sources"}],
            },
        },
        "partner_links": [
            {
                "partner_id": "fixture-partner",
                "url": "https://example.org/taxon/12345",
                "permissions": {"link_out": "allowed", "ingest": "unknown"},
                "permission_evidence": [{"source": "partner-terms", "version": "fixture"}],
                "attribution": "Fixture Partner",
            }
        ],
        "provenance": [{"source": "CALYX-467-fixture", "stable_taxon_id": "hassler:12345"}],
    }


def service(tmp_path: Path) -> SpeciesDossierService:
    return SpeciesDossierService(tmp_path / "dossiers")


def test_dossier_has_all_domains_and_graceful_degradation(tmp_path: Path):
    dossier = service(tmp_path).assemble(OWNER, payload())
    assert tuple(dossier["domains"]) == DOMAIN_NAMES
    assert dossier["domains"]["nomenclature"]["state"] == "available"
    assert dossier["domains"]["distribution"]["state"] == "unavailable"
    assert "distribution" in dossier["unavailable_domains"]
    assert dossier["graceful_degradation"] is True


def test_contradictions_and_partial_domains_are_explicit(tmp_path: Path):
    dossier = service(tmp_path).assemble(OWNER, payload())
    assert set(dossier["partial_or_review_domains"]) == {"media", "pollination"}
    assert dossier["contradiction_states"][0]["domain"] == "pollination"
    assert dossier["contradiction_states"][0]["items"]


def test_replay_is_digest_idempotent(tmp_path: Path):
    svc = service(tmp_path)
    first = svc.assemble(OWNER, payload())
    second = svc.assemble(OWNER, payload())
    assert first["dossier_digest"] == second["dossier_digest"]
    assert first == second


def test_adaptive_resolver_matches_id_name_and_alias(tmp_path: Path):
    svc = service(tmp_path)
    svc.assemble(OWNER, payload())
    by_id = svc.resolve(OWNER, "hassler:12345")
    by_name = svc.resolve(OWNER, "Cattleya skinneri")
    by_alias = svc.resolve(OWNER, "guarianthe skinneri")
    assert by_id["method"] == "stable_taxon_id"
    assert by_name["stable_taxon_id"] == "hassler:12345"
    assert by_alias["stable_taxon_id"] == "hassler:12345"


def test_adaptive_resolver_reports_ambiguity(tmp_path: Path):
    svc = service(tmp_path)
    first = payload()
    first["identity"]["aliases"] = ["Shared alias"]
    svc.assemble(OWNER, first)
    second = payload()
    second["stable_taxon_id"] = "hassler:67890"
    second["identity"]["scientific_name"] = "Cattleya maxima"
    second["identity"]["aliases"] = ["Shared alias"]
    second["provenance"] = [{"source": "fixture-2"}]
    svc.assemble(OWNER, second)
    result = svc.resolve(OWNER, "shared alias")
    assert result["state"] == "ambiguous"
    assert result["candidate_ids"] == ["hassler:12345", "hassler:67890"]


def test_partner_allowed_permission_requires_evidence(tmp_path: Path):
    svc = service(tmp_path)
    item = payload()
    item["partner_links"][0]["permission_evidence"] = []
    try:
        svc.assemble(OWNER, item)
    except ValueError as exc:
        assert str(exc) == "DOSSIER_PARTNER_PERMISSION_EVIDENCE_REQUIRED"
    else:
        raise AssertionError("allowed partner permission without evidence must fail closed")


def test_available_domain_requires_provenance(tmp_path: Path):
    svc = service(tmp_path)
    item = payload()
    item["domains"]["nomenclature"]["provenance"] = []
    try:
        svc.assemble(OWNER, item)
    except ValueError as exc:
        assert str(exc) == "DOSSIER_DOMAIN_PROVENANCE_REQUIRED:nomenclature"
    else:
        raise AssertionError("available domain without provenance must fail closed")


def test_readiness_never_authorizes_publication_or_graph_mutation(tmp_path: Path):
    svc = service(tmp_path)
    svc.assemble(OWNER, payload())
    readiness = svc.readiness(OWNER, "hassler:12345")
    assert readiness["decision"] == "DOSSIER_REVIEW_READY"
    assert readiness["production_ingestion_authorized"] is False
    assert readiness["production_graph_mutation_authorized"] is False
    assert readiness["scientific_publication_authorized"] is False
    assert readiness["production_deployment_authorized"] is False
    assert readiness["partner_permission_claims_inferred"] is False


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    created = client.put("/brain/mission-control/species-dossiers/hassler:12345", json=payload())
    assert created.status_code == 200
    fetched = client.get("/brain/mission-control/species-dossiers/hassler:12345")
    assert fetched.status_code == 200
    resolved = client.get("/brain/mission-control/species-dossiers", params={"q": "Guarianthe skinneri"})
    assert resolved.status_code == 200
    assert resolved.json()["stable_taxon_id"] == "hassler:12345"
    ready = client.get("/brain/mission-control/species-dossiers/hassler:12345/readiness")
    assert ready.status_code == 200
    assert ready.json()["decision"] == "DOSSIER_REVIEW_READY"
