import pytest

from runtime.knowledge_graph.deployment_preflight import (
    REQUIRED_PLATFORM_ROUTES,
    deployment_preflight,
    initialize_dry_run_directory,
)


def test_initializer_creates_directory_inside_declared_mount(tmp_path):
    mount = tmp_path / "render-disk"
    mount.mkdir()
    dry_runs = mount / "calyx-graph-dry-runs"

    result = initialize_dry_run_directory(
        {
            "CALYX_DRY_RUN_DIRECTORY": str(dry_runs),
            "CALYX_DRY_RUN_PERSISTENT_MOUNT": str(mount),
        }
    )

    assert result == {"initialized": True, "reason": None, "path": str(dry_runs)}
    assert dry_runs.is_dir()


def test_initializer_fails_closed_outside_declared_mount(tmp_path):
    mount = tmp_path / "render-disk"
    mount.mkdir()
    outside = tmp_path / "outside"

    with pytest.raises(RuntimeError, match="must be inside"):
        initialize_dry_run_directory(
            {
                "CALYX_DRY_RUN_DIRECTORY": str(outside),
                "CALYX_DRY_RUN_PERSISTENT_MOUNT": str(mount),
            }
        )
    assert outside.exists() is False


def test_initializer_is_noop_without_directory_configuration(tmp_path):
    result = initialize_dry_run_directory(
        {"CALYX_DRY_RUN_PERSISTENT_MOUNT": str(tmp_path)}
    )
    assert result == {
        "initialized": False,
        "reason": "directory_not_configured",
        "path": None,
    }


def test_preflight_ready_with_declared_persistent_mount(tmp_path):
    mount = tmp_path / "render-disk"
    dry_runs = mount / "dry-runs"
    dry_runs.mkdir(parents=True)

    report = deployment_preflight(
        route_paths=set(REQUIRED_PLATFORM_ROUTES),
        database_probe=lambda: None,
        env={
            "CALYX_DRY_RUN_DIRECTORY": str(dry_runs),
            "CALYX_DRY_RUN_PERSISTENT_MOUNT": str(mount),
            "RENDER_GIT_COMMIT": "abc123",
            "RENDER_SERVICE_NAME": "orchid-calyx-backend",
        },
    )
    assert report["ready_for_live_resumable_dry_run"] is True
    assert report["deployment"]["commit"] == "abc123"
    assert report["routes"]["ready"] is True
    assert report["database"]["reachable"] is True
    assert report["staging_directory"]["writable"] is True
    assert report["staging_directory"]["inside_persistent_mount"] is True
    assert report["filesystem_mutation"] is False
    assert report["blockers"] == []


def test_preflight_blocks_missing_route_database_and_undeclared_mount(tmp_path):
    dry_runs = tmp_path / "dry-runs"
    dry_runs.mkdir()

    def broken_database():
        raise RuntimeError("database unavailable")

    report = deployment_preflight(
        route_paths=set(),
        database_probe=broken_database,
        env={"CALYX_DRY_RUN_DIRECTORY": str(dry_runs)},
    )
    assert report["ready_for_live_resumable_dry_run"] is False
    assert report["routes"]["missing"]
    assert report["database"]["reachable"] is False
    assert "database_unreachable" in report["blockers"]
    assert "CALYX_DRY_RUN_PERSISTENT_MOUNT_not_configured" in report["blockers"]


def test_preflight_blocks_directory_outside_declared_mount(tmp_path):
    mount = tmp_path / "render-disk"
    mount.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()

    report = deployment_preflight(
        route_paths=set(REQUIRED_PLATFORM_ROUTES),
        database_probe=lambda: None,
        env={
            "CALYX_DRY_RUN_DIRECTORY": str(outside),
            "CALYX_DRY_RUN_PERSISTENT_MOUNT": str(mount),
        },
    )
    assert "dry_run_directory_outside_declared_persistent_mount" in report["blockers"]


def test_preflight_blocks_unconfigured_directory_without_derived_noise(tmp_path):
    fallback = tmp_path / "must-not-be-created"
    report = deployment_preflight(
        route_paths=set(REQUIRED_PLATFORM_ROUTES),
        database_probe=lambda: None,
        env={"CALYX_DRY_RUN_PERSISTENT_MOUNT": str(fallback)},
    )
    assert report["blockers"] == ["CALYX_DRY_RUN_DIRECTORY_not_configured"]
    assert report["staging_directory"]["path"] is None
    assert fallback.exists() is False
