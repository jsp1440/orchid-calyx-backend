"""Read-only full Knowledge Graph integration inventory for Mission Control and Calyx."""

from __future__ import annotations

import os

import psycopg
from fastapi import APIRouter, HTTPException

from runtime.knowledge_graph.full_domain_status import full_domain_code_readiness
from runtime.knowledge_graph.full_integration import build_publication_plan, inventory_full_graph

router = APIRouter(prefix="/api/platform/knowledge-graph", tags=["knowledge-graph-integration"])


@router.get("/full-integration")
def full_graph_integration_inventory():
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Knowledge Graph database not configured")
    try:
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                inventory = inventory_full_graph(cur)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to inventory live Knowledge Graph sources") from exc
    return {
        "inventory": inventory,
        "code_readiness": full_domain_code_readiness(),
        "publication_plan": build_publication_plan(inventory),
        "warning": "This endpoint is read-only. It does not materialize nodes or edges.",
    }
