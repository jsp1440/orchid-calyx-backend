from __future__ import annotations

from pathlib import Path

from app.routers import taxonomy_release_intake as api
from app.security import verify_owner_or_api_key
from fastapi import FastAPI
from fastapi.testclient import TestClient
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


def test_unresolved_synonym_is_queued_for_review(tmp_path: Path):
    content = b"taxon_id,scientific_name,status,accepted_name_id\n1,Cattleya labiata,synonym,\n"
    service = TaxonomyReleaseIntakeService(tmp_path)
    result = service.intake_bytes("candidate.csv", content)
    assert result["unresolved_review_count"] == 1
    queue = tmp_path / "releases" / result["release_id"] / "review_queue.json"
    assert "synonym_missing_accepted_name_id" in queue.read_text()


def test_candidate_comparison_uses_existing_preflight_diff(tmp_path: Path):
    baseline = tmp_path / "baseline.csv"
    baseline.write_bytes(BASELINE)
    service = TaxonomyReleaseIntakeService(tmp_path / "workspace")
    result = service.intake_bytes("candidate.csv", CANDIDATE, baseline_path=baseline)
    assert result["comparison"]["added"] == 1
    assert result["comparison"]["removed"] == 1
    assert result["comparison"]["baseline_unique_taxa"] == 3
    assert result["comparison"]["candidate_unique_taxa"] == 3


def test_upload_size_and_batch_size_are_bounded(tmp_path: Path):
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


def test_protected_mission_control_api_can_be_dependency_overridden_for_tests(tmp_path: Path, monkeypatch):
    service = TaxonomyReleaseIntakeService(tmp_path)
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
    release_id = intake.json()["release_id"]

    staged = client.post(
        f"/brain/mission-control/taxonomy/releases/{release_id}/stage",
        json={"batch_size": 500},
    )
    assert staged.status_code == 200
    assert staged.json()["ready_for_review"] is True

    readiness = client.get(
        f"/brain/mission-control/taxonomy/releases/{release_id}/readiness"
    )
    assert readiness.status_code == 200
    assert readiness.json()["ready_for_promotion"] is False
