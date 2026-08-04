"""Read-only deployment preflight for resumable Knowledge Graph dry runs."""
from __future__ import annotations

import os
import tempfile
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


def _directory_check(path_value: str | None) -> dict[str, Any]:
    configured = bool(path_value and path_value.strip())
    path = Path(path_value.strip()) if configured else Path("/tmp/calyx-graph-dry-runs")
    writable = False
    error = None
    try:
        path.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=path, prefix="preflight-", delete=True):
            writable = True
    except Exception as exc:
        error = str(exc)
    ephemeral = str(path).startswith("/tmp") or str(path).startswith("/var/tmp")
    return {
        "configured": configured,
        "path": str(path),
        "writable": writable,
        "appears_ephemeral": ephemeral,
        "error": error,
    }


def deployment_preflight(
    *,
    route_paths: set[str],
    database_probe: Callable[[], None],
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Evaluate deployment readiness without mutating graph or source data."""
    environment = dict(os.environ if env is None else env)
    missing_routes = sorted(REQUIRED_PLATFORM_ROUTES - route_paths)
    database_ok = False
    database_error = None
    try:
        database_probe()
        database_ok = True
    except Exception as exc:
        database_error = str(exc)

    directory = _directory_check(environment.get("CALYX_DRY_RUN_DIRECTORY"))
    blockers: list[str] = []
    if missing_routes:
        blockers.append("missing_routes:" + ",".join(missing_routes))
    if not database_ok:
        blockers.append("database_unreachable")
    if not directory["configured"]:
        blockers.append("CALYX_DRY_RUN_DIRECTORY_not_configured")
    if not directory["writable"]:
        blockers.append("dry_run_directory_not_writable")
    if directory["appears_ephemeral"]:
        blockers.append("dry_run_directory_appears_ephemeral")

    return {
        "contract": "calyx-graph-deployment-preflight-v1",
        "graph_mutation": False,
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
