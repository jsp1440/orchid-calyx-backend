from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import taxonomy_release_intake as api
from app.security import verify_owner_or_api_key
from runtime.taxonomy_release_intake import TaxonomyReleaseIntakeService

HASSLER_HEADER = (
    b"Taxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|Status|Remarks|"
    b"ConservationStatus|Photo|Orientation|Author\n"
)


def test_http_intake_rejects_oversize_before_service_materialization(
    tmp_path: Path, monkeypatch
):
    service = TaxonomyReleaseIntakeService(tmp_path / "workspace", maximum_bytes=16)
    monkeypatch.setattr(api, "_service", lambda: service)

    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    response = client.post(
        "/brain/mission-control/taxonomy/releases/intake",
        files={"source": ("oversize.csv", b"x" * 17, "text/csv")},
    )

    assert response.status_code == 413
    assert "maximum_bytes=16" in response.json()["detail"]
    assert not (tmp_path / "workspace" / "releases").exists()


def test_utf8_bom_is_removed_before_header_detection(tmp_path: Path):
    content = (
        b"\xef\xbb\xbfTaxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|"
        b"Status|Remarks|ConservationStatus|Photo|Orientation|Author\n"
        b"S|100|Cattleya labiata|||||||||||\n"
    )
    service = TaxonomyReleaseIntakeService(tmp_path)
    result = service.intake_bytes("WorldOrchids 26-08.csv", content)

    assert result["source_metadata"]["source_encoding"] == "utf-8-sig"
    assert result["source_metadata"]["source_layout"] == "hassler_worldorchids"
    assert result["accepted_name_count"] == 1
    assert result["rank_counts"] == {"species": 1}


def test_bom_prefixed_mixed_bytes_use_repair_path(tmp_path: Path):
    content = (
        b"\xef\xbb\xbfTaxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|"
        b"Status|Remarks|ConservationStatus|Photo|Orientation|Author\n"
        b"S|100|Dactylorhiza fuchsii||||||||||M\xfcller\n"
    )
    result = TaxonomyReleaseIntakeService(tmp_path).intake_bytes(
        "WorldOrchids 26-08.csv", content
    )

    assert result["source_metadata"]["source_encoding"] == "mixed_utf8_latin1_bom"
    assert result["source_metadata"]["legacy_bytes_repaired"] == 1
    normalized = (
        tmp_path / "releases" / result["release_id"] / "normalized.jsonl"
    ).read_text(encoding="utf-8")
    assert "Müller" in normalized


def test_minority_wide_hassler_row_preserves_all_extra_photo_slots(tmp_path: Path):
    ordinary = b"S|1|Cattleya labiata||||||||orchids/a.jpg|V|Author\n"
    wide = (
        b"S|2|Laelia anceps||||||||orchids/b.jpg|V|Author|"
        b"orchids/b2.jpg|H|Author Two|orchids/b3.jpg|V|Author Three\n"
    )
    service = TaxonomyReleaseIntakeService(tmp_path)
    result = service.intake_bytes(
        "WorldOrchids 26-08.csv",
        HASSLER_HEADER + ordinary + ordinary + wide,
    )

    metadata = result["source_metadata"]
    assert metadata["modal_width"] == 13
    assert metadata["maximum_width"] == 19
    assert metadata["canonical_width"] == 19
    assert metadata["nonempty_overflow_cells"] == 0

    normalized = (
        tmp_path / "releases" / result["release_id"] / "normalized.jsonl"
    ).read_text(encoding="utf-8")
    assert '"Photo2": "orchids/b2.jpg"' in normalized
    assert '"Photo3": "orchids/b3.jpg"' in normalized


def test_hassler_comparison_uses_number_as_stable_identity(tmp_path: Path):
    baseline = tmp_path / "baseline.csv"
    baseline.write_bytes(HASSLER_HEADER + b"S|100|Cattleya labiate|||||||||||\n")
    candidate = HASSLER_HEADER + b"S|100|Cattleya labiata|||||||||||\n"

    result = TaxonomyReleaseIntakeService(tmp_path / "workspace").intake_bytes(
        "WorldOrchids 26-08.csv",
        candidate,
        baseline_path=baseline,
    )

    assert result["comparison"]["added"] == 0
    assert result["comparison"]["removed"] == 0
    assert result["comparison"]["changed"] == 1
    assert result["source_metadata"]["preflight_identity_projection"] == (
        "Number->taxon_id"
    )


def test_content_addressed_replay_rejects_identity_metadata_drift(tmp_path: Path):
    content = HASSLER_HEADER + b"S|100|Cattleya labiata|||||||||||\n"
    service = TaxonomyReleaseIntakeService(tmp_path)
    first = service.intake_bytes(
        "WorldOrchids 26-08.csv",
        content,
        expected_label="26-08",
    )
    replay = service.intake_bytes(
        "WorldOrchids 26-08.csv",
        content,
        expected_label="26-08",
    )
    assert replay == first

    with pytest.raises(RuntimeError, match="immutable release identity metadata conflict"):
        service.intake_bytes(
            "renamed.csv",
            content,
            expected_label="26-08",
        )
    with pytest.raises(RuntimeError, match="immutable release identity metadata conflict"):
        service.intake_bytes(
            "WorldOrchids 26-08.csv",
            content,
            expected_label="different-label",
        )


def test_staging_uses_bounded_batch_files_and_materializes_once_complete(tmp_path: Path):
    content = (
        b"taxon_id,scientific_name,status,accepted_name_id\n"
        b"1,Cattleya labiata,accepted,\n"
        b"2,Laelia anceps,accepted,\n"
        b"3,Encyclia tampensis,accepted,\n"
    )
    service = TaxonomyReleaseIntakeService(tmp_path)
    release_id = service.intake_bytes("candidate.csv", content)["release_id"]
    root = tmp_path / "releases" / release_id

    first = service.project_staging(release_id, batch_size=1)
    assert first["staging_next_offset"] == 1
    assert not (root / "staging.jsonl").exists()
    assert len(list((root / "staging_batches").glob("*.jsonl"))) == 1

    second = service.project_staging(release_id, batch_size=1)
    assert second["staging_next_offset"] == 2
    assert len(list((root / "staging_batches").glob("*.jsonl"))) == 2

    complete = service.project_staging(release_id, batch_size=1)
    assert complete["staging_complete"] is True
    assert len((root / "staging.jsonl").read_text().splitlines()) == 3
    assert len(list((root / "staging_batches").glob("*.jsonl"))) == 3
