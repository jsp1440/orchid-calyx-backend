from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import homepage_governance as api
from app.security import verify_owner_or_api_key
from runtime.homepage_governance import HomepageGovernanceService
from runtime.species_dossier import SpeciesDossierService

OWNER = "homepage-owner"


def screenshot(label: str) -> dict[str, Any]:
    return {
        "artifact_id": f"shot-{label}",
        "checksum": f"sha256-{label}",
        "source_uri": f"artifact://screenshots/{label}",
        "captured_at": "2026-08-08T11:00:00Z",
        "viewport": {"width": 1366, "height": 1024},
        "route": "/",
    }


def audit() -> dict[str, Any]:
    return {
        "audit_id": "homepage-main",
        "deployed_revision": "deploy-sha-fixture",
        "source_screenshots": [screenshot("before")],
        "route_inventory": ["/", "/species/:id", "/atlas"],
        "findings": [{"code": "HOME-001", "summary": "Featured taxon evidence should be explicit."}],
        "evidence_anchors": [{"source": "deployed-homepage", "route": "/"}],
        "provenance": [{"captured_by": "CALYX fixture", "revision": "deploy-sha-fixture"}],
    }


def specification() -> dict[str, Any]:
    return {
        "specification_id": "homepage-redesign",
        "audit_id": "homepage-main",
        "audit_version": 1,
        "required_sections": ["hero", "featured-taxon", "atlas-entry"],
        "required_routes": ["/"],
        "required_components": ["FeaturedTaxon", "EvidenceBadge"],
        "scientific_wording_rules": [{"rule": "No unsupported conservation claims"}],
        "accessibility_requirements": [{"rule": "All informative images have alt text"}],
        "visual_requirements": [{"rule": "Responsive at tablet width"}],
        "taxonomy_requirements": [{"rule": "Featured taxon uses stable canonical ID"}],
        "media_requirements": [{"rule": "Featured media is licensed and attributed"}],
        "evidence_requirements": [{"rule": "Scientific claims expose evidence state"}],
        "evidence_anchors": [{"source": "audit", "finding": "HOME-001"}],
        "implementation_brief": {"provider": "Famous AI", "instruction": "Implement the approved specification only."},
        "provenance": [{"source": "CALYX redesign specification fixture"}],
    }


def implementation() -> dict[str, Any]:
    return {
        "implementation_id": "homepage-build-1",
        "specification_id": "homepage-redesign",
        "specification_version": 1,
        "implementation_revision": "frontend-sha-fixture",
        "manifest": {
            "sections": ["hero", "featured-taxon", "atlas-entry"],
            "routes": ["/"],
            "components": ["FeaturedTaxon", "EvidenceBadge"],
            "taxon_references": ["hassler:12345"],
            "media_references": ["media-1"],
            "evidence_references": ["evidence-1"],
        },
        "implementation_screenshots": [screenshot("after")],
        "returned_artifact_metadata": [{"artifact": "homepage-bundle", "checksum": "bundle-sha"}],
        "implementation_provider": "Famous AI",
    }


def checks(*, visual: bool = True) -> dict[str, Any]:
    return {
        "checks": {
            name: {
                "passed": visual if name == "visual" else True,
                "evidence": [{"validator": name, "receipt": f"receipt-{name}"}],
                "findings": [] if (visual or name != "visual") else ["visual regression"],
            }
            for name in ("visual", "accessibility", "scientific", "taxonomy", "media", "evidence")
        }
    }


def service(tmp_path: Path) -> HomepageGovernanceService:
    dossiers = SpeciesDossierService(tmp_path / "species-dossiers")
    dossiers.assemble(
        OWNER,
        {
            "stable_taxon_id": "hassler:12345",
            "identity": {"scientific_name": "Laelia anceps", "rank": "species"},
            "domains": {},
            "provenance": [{"source": "reviewed taxonomy fixture"}],
        },
    )
    return HomepageGovernanceService(tmp_path / "homepage", dossiers=dossiers)


def prepared(tmp_path: Path) -> HomepageGovernanceService:
    svc = service(tmp_path)
    svc.submit_audit(OWNER, audit())
    svc.submit_specification(OWNER, specification())
    svc.approve_specification(OWNER, "homepage-redesign", 1, actor=OWNER, rationale="Approved after owner review.")
    svc.receive_implementation(OWNER, implementation())
    return svc


def test_audit_and_specification_are_versioned_with_source_provenance(tmp_path: Path):
    svc = service(tmp_path)
    first = svc.submit_audit(OWNER, audit())
    second_payload = audit()
    second_payload["deployed_revision"] = "deploy-sha-fixture-2"
    second = svc.submit_audit(OWNER, second_payload)
    assert first["document_schema"] == "HomepageAuditV1"
    assert first["version"] == 1
    assert second["version"] == 2
    assert first["source_screenshots"][0]["checksum"] == "sha256-before"

    spec = svc.submit_specification(OWNER, specification())
    assert spec["document_schema"] == "HomepageRedesignSpecificationV1"
    assert spec["audit_ref"]["checksum"] == first["checksum"]
    assert spec["implementation_provider_scientific_authority"] is False


def test_implementation_requires_owner_approved_specification(tmp_path: Path):
    svc = service(tmp_path)
    svc.submit_audit(OWNER, audit())
    svc.submit_specification(OWNER, specification())
    try:
        svc.receive_implementation(OWNER, implementation())
    except ValueError as exc:
        assert str(exc) == "HOMEPAGE_SPEC_OWNER_APPROVAL_REQUIRED"
    else:
        raise AssertionError("implementation intake must require owner approval")


def test_release_eligibility_requires_all_validation_gates(tmp_path: Path):
    svc = prepared(tmp_path)
    validation = svc.validate(OWNER, "homepage-build-1", checks())
    readiness = svc.readiness(OWNER, "homepage-build-1")
    assert validation["state"] == "validated"
    assert validation["specification_match"]["passed"] is True
    assert validation["canonical_taxon_resolution"][0]["state"] == "resolved"
    assert readiness["release_eligible"] is True
    assert readiness["state"] == "release_eligible"
    assert readiness["owner_activation_required"] is True
    assert readiness["automatic_deployment_authorized"] is False
    assert readiness["scientific_publication_authorized"] is False


def test_failed_visual_validation_blocks_release(tmp_path: Path):
    svc = prepared(tmp_path)
    validation = svc.validate(OWNER, "homepage-build-1", checks(visual=False))
    readiness = svc.readiness(OWNER, "homepage-build-1")
    assert validation["state"] == "validation_failed"
    assert "failed_check:visual" in validation["blockers"]
    assert readiness["release_eligible"] is False
    assert readiness["state"] == "validation_failed"


def test_manifest_drift_blocks_release(tmp_path: Path):
    svc = service(tmp_path)
    svc.submit_audit(OWNER, audit())
    svc.submit_specification(OWNER, specification())
    svc.approve_specification(OWNER, "homepage-redesign", 1, actor=OWNER, rationale="Approved")
    item = implementation()
    item["manifest"]["components"] = ["FeaturedTaxon"]
    svc.receive_implementation(OWNER, item)
    validation = svc.validate(OWNER, "homepage-build-1", checks())
    assert "missing_component:EvidenceBadge" in validation["blockers"]
    assert svc.readiness(OWNER, "homepage-build-1")["release_eligible"] is False


def test_unresolved_canonical_taxon_blocks_release(tmp_path: Path):
    svc = prepared(tmp_path)
    stored = svc.get_implementation(OWNER, "homepage-build-1")
    stored["manifest"]["taxon_references"] = ["hassler:missing"]
    svc._write(svc._root(OWNER) / "implementations" / "homepage-build-1.json", stored)
    validation = svc.validate(OWNER, "homepage-build-1", checks())
    assert "unresolved_taxon:hassler:missing" in validation["blockers"]
    assert svc.readiness(OWNER, "homepage-build-1")["canonical_taxonomy_gate_passed"] is False


def test_passed_validation_requires_evidence_receipts(tmp_path: Path):
    svc = prepared(tmp_path)
    item = checks()
    item["checks"]["scientific"]["evidence"] = []
    try:
        svc.validate(OWNER, "homepage-build-1", item)
    except ValueError as exc:
        assert str(exc) == "HOMEPAGE_VALIDATION_EVIDENCE_REQUIRED:scientific"
    else:
        raise AssertionError("a passing scientific check without evidence must fail closed")


def test_protected_api_round_trip(tmp_path: Path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr(api, "_service", lambda: svc)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": OWNER, "auth_type": "test"}
    client = TestClient(app)

    audit_response = client.post("/brain/mission-control/homepage/audits", json=audit())
    assert audit_response.status_code == 200
    spec_response = client.post("/brain/mission-control/homepage/specifications", json=specification())
    assert spec_response.status_code == 200
    approval = client.post(
        "/brain/mission-control/homepage/specifications/homepage-redesign/versions/1/approve",
        json={"rationale": "Owner reviewed visual and scientific requirements."},
    )
    assert approval.status_code == 200
    received = client.post("/brain/mission-control/homepage/implementations", json=implementation())
    assert received.status_code == 200
    validated = client.post(
        "/brain/mission-control/homepage/implementations/homepage-build-1/validate",
        json=checks(),
    )
    assert validated.status_code == 200
    readiness = client.get("/brain/mission-control/homepage/implementations/homepage-build-1/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["release_eligible"] is True
    assert readiness.json()["unreviewed_activation_authorized"] is False
