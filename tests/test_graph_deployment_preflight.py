from runtime.knowledge_graph.deployment_preflight import (
    REQUIRED_PLATFORM_ROUTES,
    deployment_preflight,
)


def test_preflight_ready_with_persistent_directory(tmp_path):
    report = deployment_preflight(
        route_paths=set(REQUIRED_PLATFORM_ROUTES),
        database_probe=lambda: None,
        env={
            "CALYX_DRY_RUN_DIRECTORY": str(tmp_path / "dry-runs"),
            "RENDER_GIT_COMMIT": "abc123",
            "RENDER_SERVICE_NAME": "orchid-calyx-backend",
        },
    )
    assert report["ready_for_live_resumable_dry_run"] is True
    assert report["deployment"]["commit"] == "abc123"
    assert report["routes"]["ready"] is True
    assert report["database"]["reachable"] is True
    assert report["staging_directory"]["writable"] is True
    assert report["blockers"] == []


def test_preflight_blocks_missing_route_database_and_ephemeral_storage():
    def broken_database():
        raise RuntimeError("database unavailable")

    report = deployment_preflight(
        route_paths=set(),
        database_probe=broken_database,
        env={"CALYX_DRY_RUN_DIRECTORY": "/tmp/calyx-graph-dry-runs"},
    )
    assert report["ready_for_live_resumable_dry_run"] is False
    assert report["routes"]["missing"]
    assert report["database"]["reachable"] is False
    assert "database_unreachable" in report["blockers"]
    assert "dry_run_directory_appears_ephemeral" in report["blockers"]


def test_preflight_blocks_unconfigured_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    report = deployment_preflight(
        route_paths=set(REQUIRED_PLATFORM_ROUTES),
        database_probe=lambda: None,
        env={},
    )
    assert "CALYX_DRY_RUN_DIRECTORY_not_configured" in report["blockers"]
