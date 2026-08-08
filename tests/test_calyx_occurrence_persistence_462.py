from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import occurrence_persistence as api
from app.security import verify_owner_or_api_key
from runtime.occurrence_persistence import OccurrencePersistenceService


def _taxonomy_staging(path: Path) -> Path:
    rows = [
        {"taxon_key": "id:1001", "scientific_name": "Cattleya labiata"},
        {"taxon_key": "id:1002", "scientific_name": "Laelia purpurata"},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _gbif_records() -> list[dict]:
    return [
        {
            "key": 9001,
            "scientificName": "Cattleya labiata",
            "decimalLatitude": -22.9,
            "decimalLongitude": -43.2,
            "coordinateUncertaintyInMeters": 25,
            "eventDate": "2026-08-01",
            "countryCode": "BR",
            "basisOfRecord": "HUMAN_OBSERVATION",
        },
        {
            "key": 9002,
            "scientificName": "Unknown orchid",
            "decimalLatitude": 200,
            "decimalLongitude": -43.2,
            "coordinateUncertaintyInMeters": -1,
        },
    ]


def test_gbif_intake_preserves_raw_normalizes_and_reconciles_exact_taxa(tmp_path: Path):
    taxonomy = _taxonomy_staging(tmp_path / "taxonomy.jsonl")
    service = OccurrencePersistenceService(tmp_path / "occ")
    result = service.intake_records("GBIF", _gbif_records(), taxonomy_staging_path=taxonomy)

    assert result["identity"]["source"] == "gbif"
    assert result["identity"]["record_count"] == 2
    assert result["matched_taxa"] == 1
    assert result["unmatched_taxa"] == 1
    assert result["invalid_coordinate_records"] == 1
    assert result["review_queue_count"] == 1
    assert result["ready_for_publication"] is False
    assert result["knowledge_graph_mutation_authorized"] is False
    assert result["taxonomy_activation_authorized"] is False
    assert result["unbounded_harvest_authorized"] is False

    root = tmp_path / "occ" / "batches" / result["batch_id"]
    raw = [json.loads(line) for line in (root / "raw.jsonl").read_text().splitlines()]
    normalized = [json.loads(line) for line in (root / "normalized.jsonl").read_text().splitlines()]
    assert raw == _gbif_records()
    assert normalized[0]["canonical_taxon_id"] == "id:1001"
    assert normalized[0]["reconciliation_method"] == "scientific_name_exact"
    assert normalized[1]["canonical_taxon_id"] is None
    assert normalized[1]["coordinate_state"] == "invalid"
    assert normalized[1]["coordinate_uncertainty_m"] is None


def test_replay_is_content_addressed_and_staging_is_resumable_idempotent(tmp_path: Path):
    taxonomy = _taxonomy_staging(tmp_path / "taxonomy.jsonl")
    service = OccurrencePersistenceService(tmp_path / "occ")
    first = service.intake_records("gbif", _gbif_records(), taxonomy_staging_path=taxonomy)
    second = service.intake_records("gbif", _gbif_records(), taxonomy_staging_path=taxonomy)
    assert first["batch_id"] == second["batch_id"]
    assert first["identity"]["sha256"] == second["identity"]["sha256"]

    one = service.project_staging(first["batch_id"], batch_size=1)
    assert one["staging_next_offset"] == 1
    assert one["staging_complete"] is False
    assert one["decision"] == "HOLD"

    complete = service.project_staging(first["batch_id"], batch_size=1)
    assert complete["staging_complete"] is True
    assert complete["projected_unique_rows"] == 2
    assert complete["ready_for_review"] is True
    assert complete["decision"] == "REVIEW_ONLY"

    replay = service.project_staging(first["batch_id"], batch_size=500)
    assert replay == complete
    staging = tmp_path / "occ" / "batches" / first["batch_id"] / "staging.jsonl"
    assert len(staging.read_text().splitlines()) == 2


def test_taxon_key_match_precedes_name_match(tmp_path: Path):
    taxonomy = _taxonomy_staging(tmp_path / "taxonomy.jsonl")
    records = [{"key": 1, "scientificName": "wrong label", "taxon_key": "id:1002"}]
    service = OccurrencePersistenceService(tmp_path / "occ")
    result = service.intake_records("gbif", records, taxonomy_staging_path=taxonomy)
    root = tmp_path / "occ" / "batches" / result["batch_id"]
    row = json.loads((root / "normalized.jsonl").read_text().splitlines()[0])
    assert row["canonical_taxon_id"] == "id:1002"
    assert row["reconciliation_method"] == "taxon_key"


def test_unmatched_taxa_enter_read_only_review_queue(tmp_path: Path):
    service = OccurrencePersistenceService(tmp_path / "occ")
    result = service.intake_records("inaturalist", [{"id": 77, "species_guess": "Mystery orchid"}])
    queue = service.review_queue(result["batch_id"])
    assert queue["total"] == 1
    assert queue["review_write_authorized"] is False
    assert queue["items"][0]["reasons"] == ["taxon_unmatched"]
    assert queue["items"][0]["review_state"] == "pending"


def test_bounds_and_duplicate_source_identifiers_fail_closed(tmp_path: Path):
    service = OccurrencePersistenceService(tmp_path / "occ", maximum_records=1)
    try:
        service.intake_records("gbif", _gbif_records())
    except ValueError as exc:
        assert "maximum_records" in str(exc)
    else:
        raise AssertionError("oversized occurrence batch must fail")

    service = OccurrencePersistenceService(tmp_path / "occ2")
    duplicate = [{"key": 1, "scientificName": "A"}, {"key": 1, "scientificName": "B"}]
    try:
        service.intake_records("gbif", duplicate)
    except ValueError as exc:
        assert "duplicate source record identifier" in str(exc)
    else:
        raise AssertionError("duplicate source identifiers must fail")

    for invalid in (0, 5001):
        intake = service.intake_records("gbif", [{"key": invalid + 10000, "scientificName": "A"}])
        try:
            service.project_staging(intake["batch_id"], batch_size=invalid)
        except ValueError as exc:
            assert "batch_size" in str(exc)
        else:
            raise AssertionError("invalid staging batch size must fail")


def test_configured_taxonomy_path_must_exist(tmp_path: Path):
    service = OccurrencePersistenceService(tmp_path / "occ")
    try:
        service.intake_records(
            "gbif",
            [{"key": 1, "scientificName": "Cattleya labiata"}],
            taxonomy_staging_path=tmp_path / "missing.jsonl",
        )
    except ValueError as exc:
        assert "taxonomy staging artifact" in str(exc)
    else:
        raise AssertionError("missing configured taxonomy staging must fail closed")


def test_protected_mission_control_routes_use_operator_configured_taxonomy(tmp_path: Path, monkeypatch):
    taxonomy = _taxonomy_staging(tmp_path / "taxonomy.jsonl")
    service = OccurrencePersistenceService(tmp_path / "occ")
    monkeypatch.setenv("CALYX_TAXONOMY_REVIEW_STAGING_PATH", str(taxonomy))
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    intake = client.post(
        "/brain/mission-control/occurrences/intake",
        json={"source": "gbif", "records": _gbif_records()},
    )
    assert intake.status_code == 200
    payload = intake.json()
    assert payload["matched_taxa"] == 1
    batch_id = payload["batch_id"]

    staged = client.post(
        f"/brain/mission-control/occurrences/{batch_id}/stage",
        json={"batch_size": 500},
    )
    assert staged.status_code == 200
    assert staged.json()["ready_for_review"] is True
    assert staged.json()["ready_for_publication"] is False

    queue = client.get(f"/brain/mission-control/occurrences/{batch_id}/review-queue")
    assert queue.status_code == 200
    assert queue.json()["review_write_authorized"] is False

    readiness = client.get(f"/brain/mission-control/occurrences/{batch_id}/readiness")
    assert readiness.status_code == 200
    assert readiness.json()["knowledge_graph_mutation_authorized"] is False
