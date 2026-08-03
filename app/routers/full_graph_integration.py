"""Read-only full Knowledge Graph integration inventory for Mission Control and Calyx."""

from __future__ import annotations

import os

import psycopg
from fastapi import APIRouter, HTTPException

from runtime.knowledge_graph.dynamic_source_projection import build_projection
from runtime.knowledge_graph.full_domain_status import full_domain_code_readiness
from runtime.knowledge_graph.full_integration import (
    DomainInventory,
    build_publication_plan,
    inventory_full_graph,
)
from runtime.knowledge_graph.unresolved_taxon_queue import (
    queue_from_projection_plans,
    unresolved_queue_report,
)

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

    domain_objects = [DomainInventory(**item) for item in inventory.get("domains", [])]
    projection_plans = [build_projection(item) for item in domain_objects]
    projection_report = {
        "contract": "calyx-dynamic-source-projection-v1",
        "plans": [
            {
                "domain": plan.domain,
                "source": plan.source,
                "state": plan.state,
                "executable": plan.executable,
                "source_pk_column": plan.source_pk_column,
                "taxon_pk_column": plan.taxon_pk_column,
                "limitation": plan.limitation,
            }
            for plan in projection_plans
        ],
        "ready_domains": [plan.domain for plan in projection_plans if plan.executable],
        "blocked_domains": [plan.domain for plan in projection_plans if plan.state == "blocked"],
        "unavailable_domains": [plan.domain for plan in projection_plans if plan.state == "unavailable"],
        "withheld_domains": [plan.domain for plan in projection_plans if plan.state == "withheld"],
    }
    unresolved = unresolved_queue_report(queue_from_projection_plans(projection_plans))

    return {
        "inventory": inventory,
        "code_readiness": full_domain_code_readiness(),
        "source_projections": projection_report,
        "unresolved_taxon_queue": unresolved,
        "publication_plan": build_publication_plan(inventory),
        "publication_ready": (
            inventory.get("fully_integrated", False)
            and not unresolved["publication_blocked"]
            and not projection_report["blocked_domains"]
            and not projection_report["unavailable_domains"]
        ),
        "warning": "This endpoint is read-only. It does not materialize nodes or edges.",
    }
