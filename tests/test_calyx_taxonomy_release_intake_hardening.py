from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import taxonomy_release_intake as api
from app.security import verify_owner_or_api_key
from runtime.taxonomy_release_intake import TaxonomyReleaseIntakeService

HASSLER_HEADER = (
    b"Taxon|Number|Name|Literature|TrivialName|Distribution|Synonyms|Status|Remarks|"
    b"ConservationStatus|Photo|Orientation|Author\n"
)


def test_http_intake_rejects_oversize_before_service_materialization(tmp_path: Path, monkeypatch):
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
