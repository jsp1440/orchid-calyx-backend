from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers.calyx_core import router as calyx_core_router
from runtime.calyx_core_certification import (
    CONTRACT,
    build_calyx_core_certification,
    create_certification_router,
)
from runtime.image_staging import stage_image_batch
from runtime.literature_staging import stage_literature_batch
from runtime.occurrence_staging import stage_occurrence_batch


def test_occurrence_staging_reconciles_reviews_and_is_idempotent():
    records = [
        {"source_record_id": "gbif-1", "scientific_name": "Laelia anceps", "accepted_name": "Laelia anceps"},
        {"source_record_id": "gbif-2", "scientific_name": "Unknown orchid"},
    ]
    seen: set[str] = set()
    first = stage_occurrence_batch(records, source="gbif", seen_checksums=seen, canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"})
    assert len(first.staged) == 2
    assert first.staged[0].canonical_taxon_id == "taxon:laelia-anceps"
    assert first.staged[1].reconciliation_state == "unresolved"
    assert len(first.review_queue) == 1
    second = stage_occurrence_batch(records, source="gbif", seen_checksums=seen, canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"})
    assert second.staged == ()
    assert second.duplicate_skipped == 2
    assert second.idempotent is True


def test_all_non_resolved_taxon_states_enter_review_queues():
    occurrence = stage_occurrence_batch(
        [{"source_record_id": "gbif-no-map", "scientific_name": "Laelia anceps"}],
        source="gbif",
        canonical_lookup=None,
    )
    assert occurrence.staged[0].reconciliation_state == "reconciliation_unavailable"
    assert len(occurrence.review_queue) == 1

    image = stage_image_batch(
        [{"source_record_id": "inat-no-taxon", "url": "https://example.test/a.jpg", "license": "CC-BY"}],
        source="inaturalist",
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    assert image.staged[0].reconciliation_state == "review_required"
    assert len(image.review_queue) == 1

    literature = stage_literature_batch(
        [{"source_record_id": "paper-no-map", "title": "Unmapped orchid record"}],
        source="manual",
        canonical_lookup=None,
    )
    assert literature.staged[0].reconciliation_state == "reconciliation_unavailable"
    assert len(literature.review_queue) == 1


def test_image_staging_enforces_license_allowlist():
    result = stage_image_batch(
        [
            {"source_record_id": "inat-1", "url": "https://example.test/allowed.jpg", "license": "CC-BY", "taxon_name": "Laelia anceps"},
            {"source_record_id": "inat-2", "url": "https://example.test/rejected.jpg", "license": "all-rights-reserved", "taxon_name": "Laelia anceps"},
        ],
        source="inaturalist",
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].license == "cc-by"
    assert len(result.rejected) == 1
    assert result.summary()["no_production_mutation"] is True


def test_literature_staging_preserves_evidence_and_provenance():
    result = stage_literature_batch(
        [
            {
                "source_record_id": "paper-1",
                "title": "Pollination of Laelia anceps",
                "authors": ["A. Botanist"],
                "publication_year": "2024",
                "taxon_name": "Laelia anceps",
                "raw_text": "Pollination evidence span.",
                "evidence_spans": [{"start": 0, "end": 12, "page": 4}],
                "extraction_manifest": {"extractor": "evidence-v1"},
            }
        ],
        source="manual",
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    record = result.staged[0]
    assert record.canonical_taxon_id == "taxon:laelia-anceps"
    assert record.evidence_spans == ({"start": 0, "end": 12, "page": 4},)
    assert record.content_hash and len(record.content_hash) == 64
    assert record.extraction_manifest["extractor"] == "evidence-v1"
    assert result.summary()["candidate_knowledge_governance_intact"] is True


def test_certification_reports_operational_readiness_without_overstatement(tmp_path: Path):
    taxonomy_root = tmp_path / "taxonomy"
    literature_root = tmp_path / "literature"
    taxonomy_root.mkdir()
    literature_root.mkdir()
    report = build_calyx_core_certification(taxonomy_root=taxonomy_root, literature_root=literature_root, deployed_commit="test-commit")
    assert report["contract"] == CONTRACT
    assert report["deployed_commit"] == "test-commit"
    assert report["no_production_mutation"] is True
    assert report["overall_status"] == "partial_operational_readiness"
    assert report["pipeline_domains"]["occurrences"]["state"] == "staging_module_available"
    assert report["pipeline_domains"]["occurrences"]["operational_status"] == "partial"
    assert report["pipeline_domains"]["occurrences"]["operational_blockers"]
    assert report["pipeline_domains"]["licensed_images"]["license_enforcement"] == "allowlist_active"
    assert report["pipeline_domains"]["licensed_images"]["operational_status"] == "partial"
    assert report["pipeline_domains"]["licensed_images"]["operational_blockers"]
    assert report["publication_safeguards"]["automatic_publication"] is False
    assert "CALYX_OWNER_ACCESS_CODE" in report["configuration_presence"]
    assert "CALYX_OWNER_SESSION_SECRET" in report["configuration_presence"]


def test_certification_route_is_owner_gated_and_mounted_under_api():
    called = {"auth": 0}

    def fake_owner():
        called["auth"] += 1
        return {"actor": "owner"}

    app = FastAPI()
    app.include_router(create_certification_router(fake_owner), prefix="/api")
    response = TestClient(app).get("/api/mission-control/calyx-core/certification")
    assert response.status_code == 200
    assert called["auth"] == 1
    assert response.json()["no_production_mutation"] is True

    mounted_paths = {route.path for route in calyx_core_router.routes}
    assert "/api/mission-control/calyx-core/certification" in mounted_paths
