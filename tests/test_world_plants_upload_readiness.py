from runtime.world_plants_upload_readiness import evaluate_upload_readiness


def test_readiness_fails_closed_when_any_gate_is_missing(tmp_path):
    result = evaluate_upload_readiness(
        intake_root=tmp_path / "missing",
        owner_auth_configured=True,
        database_configured=True,
        staging_schema_confirmed=True,
        deployed_route_confirmed=True,
        smoke_fixture_confirmed=True,
    )
    assert result.ready is False
    assert result.instruction.startswith("Do not upload")


def test_readiness_allows_upload_only_after_every_gate_passes(tmp_path):
    intake = tmp_path / "taxonomy-releases"
    intake.mkdir()
    result = evaluate_upload_readiness(
        intake_root=intake,
        owner_auth_configured=True,
        database_configured=True,
        staging_schema_confirmed=True,
        deployed_route_confirmed=True,
        smoke_fixture_confirmed=True,
    )
    assert result.ready is True
    assert "taxonomy-releases" in result.instruction
    assert all(check.passed for check in result.checks)
