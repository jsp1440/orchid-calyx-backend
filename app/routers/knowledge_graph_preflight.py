"""Owner-authenticated deployment preflight for live Knowledge Graph dry runs."""
from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, Request

from app.security import verify_owner_or_api_key
from runtime.knowledge_graph.deployment_preflight import (
    deployment_preflight,
    initialize_dry_run_directory,
)

# Router modules are imported during application startup. Initialize the
# configured staging root once, before any dry-run or preflight request.
initialize_dry_run_directory()

router = APIRouter(prefix="/api/platform/knowledge-graph", tags=["knowledge-graph-integration"])


@router.get("/deployment-preflight", dependencies=[Depends(verify_owner_or_api_key)])
def knowledge_graph_deployment_preflight(request: Request):
    route_paths = {route.path for route in request.app.routes if hasattr(route, "path")}

    def database_probe() -> None:
        from app.routers.full_graph_integration import _dsn

        with psycopg.connect(_dsn(), connect_timeout=8) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()

    return deployment_preflight(route_paths=route_paths, database_probe=database_probe)
