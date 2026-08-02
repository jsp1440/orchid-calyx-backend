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
    assert statuses["owner_promotion_approval"] == "blocked"
    assert "mission-control?view=taxonomy-releases" in report["instruction"]
