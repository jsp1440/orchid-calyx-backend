import json
from pathlib import Path

from runtime.world_plants_readiness_api import build_taxonomy_readiness_report


def test_readiness_fails_closed_without_deployment_confirmations(
    tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("CALYX_TAXONOMY_STORAGE_PERSISTENT", raising=False)
    monkeypatch.delenv("CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED", raising=False)
    monkeypatch.delenv("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    report = build_taxonomy_readiness_report(intake_root=tmp_path)
    statuses = {gate["name"]: gate["status"] for gate in report["gates"]}

    assert report["ready_for_upload"] is False
    assert report["ready_for_promotion"] is False
    assert report["pipeline_state"] == "deployment_gates_blocking_intake"
    assert report["next_job"]["job"] == "resolve_taxonomy_intake_gates"
    assert statuses["persistent_intake_storage"] == "blocked"
    assert statuses["staging_schema"] == "blocked"
    assert statuses["smoke_fixture"] == "blocked"
    assert statuses["rollback_certification"] == "passed"


def test_readiness_passes_upload_gates_with_verified_environment(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("CALYX_TAXONOMY_STORAGE_PERSISTENT", "true")
    monkeypatch.setenv("CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED", "true")
    monkeypatch.setenv("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")

    report = build_taxonomy_readiness_report(intake_root=tmp_path)
    statuses = {gate["name"]: gate["status"] for gate in report["gates"]}

    assert report["ready_for_upload"] is True
    assert report["ready_for_promotion"] is False
    assert report["pipeline_state"] == "ready_for_release_upload"
    assert report["next_job"]["job"] == "upload_world_orchids_release"
    assert statuses["owner_promotion_approval"] == "blocked"
    assert "Mission Control taxonomy intake" in report["instruction"]


def test_inspected_release_reports_staging_schema_governance_boundary(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("CALYX_TAXONOMY_STORAGE_PERSISTENT", "true")
    monkeypatch.delenv("CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED", raising=False)
    monkeypatch.setenv("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    release_dir = tmp_path / "release-sha"
    release_dir.mkdir()
    (release_dir / "report.json").write_text(
        json.dumps(
            {
                "release_id": "release-sha",
                "state": "inspected",
                "snapshot": {
                    "version_label": "26-08",
                    "filename": "WorldOrchids 26-08 (Aug 2 2026).csv",
                    "acquired_at": "2026-08-02",
                },
            }
        ),
        encoding="utf-8",
    )

    report = build_taxonomy_readiness_report(intake_root=tmp_path)

    assert report["pipeline_state"] == "release_inspected_staging_schema_blocked"
    assert report["next_job"]["job"] == "verify_taxonomy_staging_schema"
    assert report["next_job"]["requires_owner_approval"] is True
    assert report["next_job"]["governance_boundary"] == "production_database_migration"
    assert report["latest_inspected_release"]["release_id"] == "release-sha"


def test_inspected_release_ready_for_bounded_staging_after_verified_gates(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("CALYX_TAXONOMY_STORAGE_PERSISTENT", "true")
    monkeypatch.setenv("CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED", "true")
    monkeypatch.setenv("CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED", "true")
    monkeypatch.setenv("DATABASE_URL", "postgresql://redacted")
    release_dir = tmp_path / "release-sha"
    release_dir.mkdir()
    (release_dir / "report.json").write_text(
        json.dumps(
            {
                "release_id": "release-sha",
                "state": "inspected",
                "snapshot": {
                    "version_label": "26-08",
                    "filename": "WorldOrchids 26-08 (Aug 2 2026).csv",
                    "acquired_at": "2026-08-02",
                },
            }
        ),
        encoding="utf-8",
    )

    report = build_taxonomy_readiness_report(intake_root=tmp_path)

    assert report["pipeline_state"] == "release_inspected_ready_for_bounded_staging"
    assert report["next_job"]["job"] == "stage_next_taxonomy_batch"
    assert report["next_job"]["maximum_batch_size"] == 2000
    assert report["next_job"]["requires_owner_approval"] is False
