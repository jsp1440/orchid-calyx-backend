from pathlib import Path

from runtime.world_plants_ingest import parse_world_orchids_release

FIXTURE = Path("tests/fixtures/world_plants_activation_smoke.csv")


def test_smoke_fixture_is_valid_and_unmistakably_noncanonical():
    result = parse_world_orchids_release(FIXTURE.read_bytes())
    assert result.summary()["rows"] == 1
    assert result.summary()["issues"] == 0
    row = result.rows[0]
    assert row.values["world_plants_number"] == "ACTIVATION-SMOKE-0001"
    assert "smoke test" in row.values["name"].casefold()


def test_activation_scripts_do_not_reference_production_release_filename():
    migration_script = Path("scripts/apply_world_plants_staging.py").read_text()
    smoke_script = Path("scripts/smoke_world_plants_activation.py").read_text()
    forbidden = "WorldOrchids 26-08 (Aug 2 2026).csv"
    assert forbidden not in migration_script
    assert forbidden not in smoke_script
    assert "ready_for_promotion" in smoke_script
    assert "PROMOTION_MUST_REMAIN_BLOCKED" in smoke_script


def test_activation_workflow_is_manual_and_environment_protected():
    workflow = Path(".github/workflows/calyx-taxonomy-activation-002.yml").read_text()
    assert "workflow_dispatch:" in workflow
    assert "environment: production" in workflow
    assert "scripts/apply_world_plants_staging.py" in workflow
    assert "scripts/smoke_world_plants_activation.py" in workflow
    assert "push:" not in workflow
