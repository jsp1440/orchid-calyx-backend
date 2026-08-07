from __future__ import annotations

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
        {
            "source_record_id": "gbif-1",
            "scientific_name": "Laelia anceps",
            "accepted_name": "Laelia anceps",
            "latitude": 18.5,
            "longitude": -97.2,
        },
        {
            "source_record_id": "gbif-2",
            "scientific_name": "Unknown orchid",
        },
    ]
    seen: set[str] = set()
    first = stage_occurrence_batch(
        records,
        source="gbif",
        seen_checksums=seen,
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    assert len(first.staged) == 2
    assert first.staged[0].canonical_taxon_id == "taxon:laelia-anceps"
    assert first.staged[0].reconciliation_state == "resolved"
    assert first.staged[1].reconciliation_state == "unresolved"
    assert len(first.review_queue) == 1
    assert first.summary()["no_production_mutation"] is True

    second = stage_occurrence_batch(
        records,
        source="gbif",
        seen_checksums=seen,
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    assert second.staged == ()
    assert second.duplicate_skipped == 2
    assert second.idempotent is True


def test_image_staging_enforces_license_allowlist_before_staging():
    result = stage_image_batch(
        [
            {
                "source_record_id": "inat-1",
                "url": "https://example.test/allowed.jpg",
                "license": "CC-BY",
                "taxon_name": "Laelia anceps",
                "creator": "Example Observer",
            },
            {
                "source_record_id": "inat-2",
                "url": "https://example.test/rejected.jpg",
                "license": "all-rights-reserved",
                "taxon_name": "Laelia anceps",
            },
        ],
        source="inaturalist",
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    assert len(result.staged) == 1
    assert result.staged[0].license == "cc-by"
    assert result.staged[0].canonical_taxon_id == "taxon:laelia-anceps"
    assert len(result.rejected) == 1
    assert "License" in result.rejected[0].reason
    assert result.summary()["no_production_mutation"] is True


def test_literature_staging_preserves_evidence_spans_hash_and_review_queue():
    result = stage_literature_batch(
        [
            {
                "source_record_id": "doi:10.1/example",
                "doi": "10.1/example",
                "title": "Pollination of Laelia anceps",
                "authors": ["A. Botanist"],
                "publication_year": "2024",
                "taxon_name": "Laelia anceps",
                "raw_text": "Pollination evidence span.",
                "evidence_spans": [{"start": 0, "end": 12, "page": 4}],
                "extraction_manifest": {"extractor": "evidence-v1"},
            },
            {
                "source_record_id": "paper-2",
                "title": "An unresolved orchid",
                "taxon_name": "Unknown orchid",
            },
        ],
        source="manual",
        canonical_lookup={"Laelia anceps": "taxon:laelia-anceps"},
    )
    first = result.staged[0]
    assert first.canonical_taxon_id == "taxon:laelia-anceps"
    assert first.evidence_spans == ({"start": 0, "end": 12, "page": 4},)
    assert first.content_hash and len(first.content_hash) == 64
    assert first.extraction_manifest["extractor"] == "evidence-v1"
    assert len(result.review_queue) == 1
    assert result.summary()["candidate_knowledge_governance_intact"] is True


def test_certification_is_read_only_and_reports_current_modules(tmp_path: Path):
    taxonomy_root = tmp_path / "taxonomy"
    literature_root = tmp_path / "literature"
    taxonomy_root.mkdir()
    literature_root.mkdir()
    report = build_calyx_core_certification(
        taxonomy_root=taxonomy_root,
        literature_root=literature_root,
        deployed_commit="test-commit",
    )
    assert report["contract"] == CONTRACT
    assert report["deployed_commit"] == "test-commit"
    assert report["no_production_mutation"] is True
    assert report["pipeline_domains"]["occurrences"]["state"] == "staging_pipeline_ready"
    assert report["pipeline_domains"]["licensed_images"]["license_enforcement"] == "allowlist_active"
    assert report["publication_safeguards"]["automatic_publication"] is False


def test_certification_route_is_owner_gated_and_mounted_under_api():
    called = {"auth": 0}

    def fake_owner():
        called["auth"] += 1
        return {"role": "owner"}

    app = FastAPI()
    app.include_router(create_certification_router(fake_owner), prefix="/api")
    response = TestClient(app).get("/api/mission-control/calyx-core/certification")
    assert response.status_code == 200
    assert called["auth"] == 1
    assert response.json()["no_production_mutation"] is True

    mounted_paths = {route.path for route in calyx_core_router.routes}
    assert "/api/mission-control/calyx-core/certification" in mounted_paths
