"""Read-only deployment preflight for resumable Knowledge Graph dry runs."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable


REQUIRED_PLATFORM_ROUTES = {
    "/api/platform/knowledge-graph/dry-runs",
    "/api/platform/knowledge-graph/dry-runs/{run_id}",
    "/api/platform/knowledge-graph/dry-runs/{run_id}/resume",
    "/api/platform/knowledge-graph/dry-runs/{run_id}/cancel",
    "/api/platform/knowledge-graph/persisted-audit",
}


def _commit_metadata(env: dict[str, str]) -> dict[str, str | None]:
    return {
        "commit": env.get("RENDER_GIT_COMMIT") or env.get("GIT_COMMIT") or env.get("SOURCE_VERSION"),
        "service": env.get("RENDER_SERVICE_NAME") or env.get("SERVICE_NAME"),
        "environment": env.get("RENDER_SERVICE_TYPE") or env.get("ENVIRONMENT"),
    }


def _inside_mount(path: Path, mount: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(mount.resolve(strict=False))
        return True
    except ValueError:
        return False


def _directory_check(path_value: str | None, mount_value: str | None) -> dict[str, Any]:
    configured = bool(path_value and path_value.strip())
    mount_configured = bool(mount_value and mount_value.strip())
    if not configured:
        return {
            "configured": False,
            "path": None,
            "exists": False,
            "is_directory": False,
            "writable": False,
            "persistent_mount_configured": mount_configured,
            "persistent_mount": mount_value.strip() if mount_configured else None,
            "inside_persistent_mount": False,
            "error": None,
        }

    path = Path(path_value.strip())
    mount = Path(mount_value.strip()) if mount_configured else None
    exists = path.exists()
    is_directory = path.is_dir() if exists else False
    writable = bool(is_directory and os.access(path, os.W_OK | os.X_OK))
    inside_mount = bool(mount and _inside_mount(path, mount))

    return {
        "configured": True,
        "path": str(path),
        "exists": exists,
        "is_directory": is_directory,
        "writable": writable,
        "persistent_mount_configured": mount_configured,
        "persistent_mount": str(mount) if mount else None,
        "inside_persistent_mount": inside_mount,
        "error": None,
    }


def deployment_preflight(
    *,
    route_paths: set[str],
    database_probe: Callable[[], None],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate deployment readiness without graph, source, or filesystem writes."""
    environment = dict(os.environ if env is None else env)
    missing_routes = sorted(REQUIRED_PLATFORM_ROUTES - route_paths)
    database_ok = False
    database_error = None
    try:
        database_probe()
        database_ok = True
    except Exception as exc:
        database_error = str(exc)

    directory = _directory_check(
        environment.get("CALYX_DRY_RUN_DIRECTORY"),
        environment.get("CALYX_DRY_RUN_PERSISTENT_MOUNT"),
    )
    blockers: list[str] = []
    if missing_routes:
        blockers.append("missing_routes:" + ",".join(missing_routes))
    if not database_ok:
        blockers.append("database_unreachable")
    if not directory["configured"]:
        blockers.append("CALYX_DRY_RUN_DIRECTORY_not_configured")
    else:
        if not directory["persistent_mount_configured"]:
            blockers.append("CALYX_DRY_RUN_PERSISTENT_MOUNT_not_configured")
        elif not directory["inside_persistent_mount"]:
            blockers.append("dry_run_directory_outside_declared_persistent_mount")
        if not directory["exists"]:
            blockers.append("dry_run_directory_missing")
        elif not directory["is_directory"]:
            blockers.append("dry_run_path_is_not_directory")
        elif not directory["writable"]:
            blockers.append("dry_run_directory_not_writable")

    return {
        "contract": "calyx-graph-deployment-preflight-v2",
        "graph_mutation": False,
        "filesystem_mutation": False,
        "deployment": _commit_metadata(environment),
        "routes": {
            "required": sorted(REQUIRED_PLATFORM_ROUTES),
            "missing": missing_routes,
            "ready": not missing_routes,
        },
        "database": {"reachable": database_ok, "error": database_error},
        "staging_directory": directory,
        "ready_for_live_resumable_dry_run": not blockers,
        "blockers": blockers,
    }
