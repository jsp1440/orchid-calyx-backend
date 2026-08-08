from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import licensed_media_persistence as api
from app.security import verify_owner_or_api_key
from runtime.licensed_media_persistence import LicensedMediaPersistenceService


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _taxonomy(path: Path) -> Path:
    rows = [
        {"taxon_key": "id:1001", "scientific_name": "Cattleya labiata"},
        {"taxon_key": "id:1002", "scientific_name": "Laelia purpurata"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _record(**overrides):
    record = {
        "provider": "Wikimedia Commons",
        "source_url": "https://commons.wikimedia.org/wiki/File:Cattleya.jpg",
        "creator": "Example Photographer",
        "attribution": "Example Photographer / Wikimedia Commons",
        "license": "CC BY 4.0",
        "sha256": _sha("cattleya-image"),
        "media_type": "image/jpeg",
        "acquired_at": "2026-08-07T20:00:00Z",
        "scientific_name": "Cattleya labiata",
    }
    record.update(overrides)
    return record


def test_intake_enforces_license_attribution_and_reconciles_taxon(tmp_path: Path):
    service = LicensedMediaPersistenceService(tmp_path / "media")
    result = service.intake_records([_record()], taxonomy_staging_path=_taxonomy(tmp_path / "taxa.jsonl"))

    assert result["matched_taxa"] == 1
    assert result["unmatched_taxa"] == 0
    assert result["review_queue_count"] == 0
    assert result["artifact_registry_artifact_count"] == 1
    assert result["ready_for_publication"] is False
    assert result["knowledge_graph_mutation_authorized"] is False

    root = tmp_path / "media" / "batches" / result["batch_id"]
    normalized = json.loads((root / "normalized.jsonl").read_text().strip())
    assert normalized["license"] == "cc-by-4.0"
    assert normalized["canonical_taxon_id"] == "id:1001"
    assert normalized["attribution"].startswith("Example Photographer")
    snapshot = json.loads((root / "artifact_registry_snapshot.json").read_text())
    assert snapshot["artifact_count"] == 1


def test_unlicensed_and_insufficient_attribution_fail_closed(tmp_path: Path):
    service = LicensedMediaPersistenceService(tmp_path / "media")
    for record, expected in (
        (_record(license="all rights reserved"), "MEDIA_LICENSE_NOT_ALLOWED"),
        (_record(creator=""), "MEDIA_ATTRIBUTION_REQUIRED"),
        (_record(attribution=""), "MEDIA_ATTRIBUTION_REQUIRED"),
    ):
        try:
            service.intake_records([record])
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid rights record must fail closed")


def test_duplicate_url_hash_and_conflicts_enter_review(tmp_path: Path):
    service = LicensedMediaPersistenceService(tmp_path / "media")
    first = _record()
    duplicate_url = _record()
    duplicate_content_new_url = _record(source_url="https://example.org/same-image.jpg")
    conflict = _record(sha256=_sha("different-content"))
    result = service.intake_records([first, duplicate_url, duplicate_content_new_url, conflict])

    assert result["duplicate_url_count"] == 1
    assert result["duplicate_content_count"] == 1
    assert result["conflicting_url_checksum_count"] == 1
    queue = service.review_queue(result["batch_id"], limit=100)
    reasons = [reason for item in queue["items"] for reason in item["reasons"]]
    assert "duplicate_url" in reasons
    assert "duplicate_content_different_url" in reasons
    assert "conflicting_url_checksum" in reasons
    assert queue["review_write_authorized"] is False


def test_unmatched_taxon_is_explicit_review_item(tmp_path: Path):
    service = LicensedMediaPersistenceService(tmp_path / "media")
    result = service.intake_records([_record(scientific_name="Mystery orchid")], taxonomy_staging_path=_taxonomy(tmp_path / "taxa.jsonl"))
    assert result["unmatched_taxa"] == 1
    queue = service.review_queue(result["batch_id"])
    assert queue["items"][0]["reasons"] == ["taxon_unmatched"]


def test_staging_is_bounded_resumable_and_idempotent(tmp_path: Path):
    service = LicensedMediaPersistenceService(tmp_path / "media")
    records = [
        _record(source_url=f"https://example.org/{index}.jpg", sha256=_sha(str(index)))
        for index in range(3)
    ]
    result = service.intake_records(records)
    batch_id = result["batch_id"]

    first = service.project_staging(batch_id, batch_size=1)
    assert first["staging_next_offset"] == 1
    assert first["staging_complete"] is False
    complete = service.project_staging(batch_id, batch_size=5)
    assert complete["staging_complete"] is True
    assert complete["projected_unique_rows"] == 3
    assert complete["decision"] == "REVIEW_ONLY"
    replay = service.project_staging(batch_id, batch_size=5)
    assert replay == complete


def test_protected_routes_use_operator_configured_taxonomy(tmp_path: Path, monkeypatch):
    taxonomy = _taxonomy(tmp_path / "taxa.jsonl")
    service = LicensedMediaPersistenceService(tmp_path / "media")
    monkeypatch.setenv("CALYX_TAXONOMY_REVIEW_STAGING_PATH", str(taxonomy))
    monkeypatch.setattr(api, "_service", lambda: service)

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    response = client.post("/brain/mission-control/media/intake", json={"records": [_record()]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["matched_taxa"] == 1
    batch_id = payload["batch_id"]

    staged = client.post(f"/brain/mission-control/media/{batch_id}/stage", json={"batch_size": 500})
    assert staged.status_code == 200
    assert staged.json()["ready_for_review"] is True
    readiness = client.get(f"/brain/mission-control/media/{batch_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["ready_for_publication"] is False


def test_bounds_and_invalid_metadata_fail_closed(tmp_path: Path):
    service = LicensedMediaPersistenceService(tmp_path / "media", maximum_records=1)
    try:
        service.intake_records([_record(), _record(source_url="https://example.org/two.jpg", sha256=_sha("two"))])
    except ValueError as exc:
        assert "maximum_records" in str(exc)
    else:
        raise AssertionError("oversized batch must fail")

    normal = LicensedMediaPersistenceService(tmp_path / "normal")
    for record, expected in (
        (_record(source_url="not-a-url"), "MEDIA_SOURCE_URL_INVALID"),
        (_record(sha256="bad"), "MEDIA_SHA256_INVALID"),
        (_record(provider=""), "MEDIA_PROVIDER_REQUIRED"),
        (_record(acquired_at=""), "MEDIA_ACQUISITION_TIME_REQUIRED"),
    ):
        try:
            normal.intake_records([record])
        except ValueError as exc:
            assert expected in str(exc)
        else:
            raise AssertionError("invalid media metadata must fail")
