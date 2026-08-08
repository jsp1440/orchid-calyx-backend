from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import taxonomy_release_intake as api
from app.security import verify_owner_or_api_key
from runtime.taxonomy_release_intake import TaxonomyReleaseIntakeService

CANDIDATE = b"""taxon_id,scientific_name,status,accepted_name_id
1,Cattleya labiata,accepted,
2,Laelia purpurata,accepted,
3,Cattleya labiate,synonym,1
"""

BASELINE = b"""taxon_id,scientific_name,status,accepted_name_id
1,Cattleya labiata,accepted,
2,Laelia purpurata,accepted,
4,Old orchid,accepted,
"""


def test_intake_is_content_addressed_review_only_and_replay_idempotent(tmp_path: Path):
    service = TaxonomyReleaseIntakeService(tmp_path)
    first = service.intake_bytes("WorldOrchids 26-08.csv", CANDIDATE, expected_label="26-08")
    second = service.intake_bytes("WorldOrchids 26-08.csv", CANDIDATE, expected_label="26-08")

    assert first["release_id"] == second["release_id"]
    assert first["identity"]["sha256"] == second["identity"]["sha256"]
    assert first["source_sha256"] == first["identity"]["sha256"]
    assert len(first["normalized_sha256"]) == 64
    assert first["accepted_name_count"] == 2
    assert first["synonym_count"] == 1
    assert first["ready_for_promotion"] is False
    assert first["taxonomy_activation_authorized"] is False
    assert first["production_relink_authorized"] is False
    assert first["knowledge_graph_publication_authorized"] is False

    root = tmp_path / "releases" / first["release_id"]
    assert (root / "source" / "WorldOrchids_26-08.csv").read_bytes() == CANDIDATE
    assert len((root / "normalized.jsonl").read_text().splitlines()) == 3


def test_bounded_staging_resumes_and_becomes_review_ready_without_promotion(tmp_path: Path):
    service = TaxonomyReleaseIntakeService(tmp_path)
    intake = service.intake_bytes("candidate.csv", CANDIDATE)
    release_id = intake["release_id"]

    one = service.project_staging(release_id, batch_size=1)
    assert one["staging_next_offset"] == 1
    assert one["staging_complete"] is False
    assert one["decision"] == "HOLD"

    two = service.project_staging(release_id, batch_size=1)
    assert two["staging_next_offset"] == 2

    complete = service.project_staging(release_id, batch_size=2)
    assert complete["staging_complete"] is True
    assert complete["ready_for_review"] is True
    assert complete["decision"] == "REVIEW_ONLY"
    assert complete["ready_for_promotion"] is False

    replay = service.project_staging(release_id, batch_size=2)
    assert replay == complete
    staging = tmp_path / "releases" / release_id / "staging.jsonl"
    assert len(staging.read_text().splitlines()) == 3


def test_unresolved_synonym_is_queued_for_read_only_review(tmp_path: Path):
    content = b"taxon_id,scientific_name,status,accepted_name_id\n1,Cattleya labiata,synonym,\n"
    service = TaxonomyReleaseIntakeService(tmp_path)
    result = service.intake_bytes("candidate.csv", content)
    assert result["unresolved_review_count"] == 1

    queue = service.review_queue(result["release_id"], limit=25)
    assert queue["total"] == 1
    assert queue["review_write_authorized"] is False
    assert queue["items"][0]["reason"] == "synonym_missing_accepted_name_id"
    assert queue["items"][0]["review_state"] == "pending"


def test_malformed_and_unresolved_counts_are_explicit(tmp_path: Path):
    content = b"""taxon_id,scientific_name,status,accepted_name_id
1,cattleya Labiata,accepted,
2,Cattleya labiata,unknown,
"""
    service = TaxonomyReleaseIntakeService(tmp_path)
    result = service.intake_bytes("candidate.csv", content)
    assert result["malformed_taxon_count"] == 1
    assert result["unresolved_review_count"] == 1


def test_candidate_comparison_preserves_baseline_identity(tmp_path: Path):
    baseline = tmp_path / "baseline.csv"
    baseline.write_bytes(BASELINE)
    service = TaxonomyReleaseIntakeService(tmp_path / "workspace")
    result = service.intake_bytes("candidate.csv", CANDIDATE, baseline_path=baseline)
    assert result["comparison"]["added"] == 1
    assert result["comparison"]["removed"] == 1
    assert result["comparison"]["baseline_unique_taxa"] == 3
    assert result["comparison"]["candidate_unique_taxa"] == 3
    assert result["baseline_filename"] == "baseline.csv"
    assert len(result["baseline_sha256"]) == 64


def test_upload_batch_and_review_queue_bounds_are_enforced(tmp_path: Path):
    service = TaxonomyReleaseIntakeService(tmp_path, maximum_bytes=5)
    try:
        service.intake_bytes("candidate.csv", CANDIDATE)
    except ValueError as exc:
        assert "maximum_bytes" in str(exc)
    else:
        raise AssertionError("oversized upload must fail")

    normal = TaxonomyReleaseIntakeService(tmp_path / "normal")
    release_id = normal.intake_bytes("candidate.csv", CANDIDATE)["release_id"]
    for invalid in (0, 5001):
        try:
            normal.project_staging(release_id, batch_size=invalid)
        except ValueError as exc:
            assert "batch_size" in str(exc)
        else:
            raise AssertionError("invalid batch size must fail")

    for offset, limit in ((-1, 10), (0, 0), (0, 501)):
        try:
            normal.review_queue(release_id, offset=offset, limit=limit)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid review queue bounds must fail")


def test_protected_mission_control_api_uses_configured_active_baseline_and_review_queue(
    tmp_path: Path, monkeypatch
):
    service = TaxonomyReleaseIntakeService(tmp_path / "workspace")
    baseline = tmp_path / "active.csv"
    baseline.write_bytes(CANDIDATE)
    monkeypatch.setenv("CALYX_TAXONOMY_ACTIVE_BASELINE_PATH", str(baseline))
    monkeypatch.setattr(api, "_service", lambda: service)
    app = FastAPI()
    app.include_router(api.router)
    app.dependency_overrides[verify_owner_or_api_key] = lambda: {"actor": "test-owner"}
    client = TestClient(app)

    intake = client.post(
        "/brain/mission-control/taxonomy/releases/intake",
        files={"source": ("candidate.csv", CANDIDATE, "text/csv")},
        data={"expected_label": "26-08"},
    )
    assert intake.status_code == 200
    intake_payload = intake.json()
    assert intake_payload["baseline_filename"] == "active.csv"
    assert len(intake_payload["baseline_sha256"]) == 64
    assert intake_payload["comparison"]["added"] == 0
    assert intake_payload["comparison"]["removed"] == 0
    release_id = intake_payload["release_id"]

    staged = client.post(
        f"/brain/mission-control/taxonomy/releases/{release_id}/stage",
        json={"batch_size": 500},
    )
    assert staged.status_code == 200
    assert staged.json()["ready_for_review"] is True

    queue = client.get(
        f"/brain/mission-control/taxonomy/releases/{release_id}/review-queue"
    )
    assert queue.status_code == 200
    assert queue.json()["review_write_authorized"] is False

    readiness = client.get(
        f"/brain/mission-control/taxonomy/releases/{release_id}/readiness"
    )
    assert readiness.status_code == 200
    assert readiness.json()["ready_for_promotion"] is False
