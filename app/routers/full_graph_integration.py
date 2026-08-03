"""Full Knowledge Graph inventory, staged dry run, and persisted audit routes."""

from __future__ import annotations

import os

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.knowledge_graph.adapters import adapters_by_domain
from runtime.knowledge_graph.controlled_dry_run import (
    publication_authorization_payload,
    run_controlled_dry_run,
)
from runtime.knowledge_graph.dynamic_source_projection import build_projection
from runtime.knowledge_graph.full_domain_status import full_domain_code_readiness
from runtime.knowledge_graph.full_integration import (
    DomainInventory,
    build_publication_plan,
    inventory_full_graph,
)
from runtime.knowledge_graph.post_publication_audit import persisted_graph_audit
from runtime.knowledge_graph.repository import PostgresGraphRepository
from runtime.knowledge_graph.source_registry import enabled_queries
from runtime.knowledge_graph.sources import PostgresSourceProvider
from runtime.knowledge_graph.unresolved_taxon_queue import (
    queue_from_projection_plans,
    unresolved_queue_report,
)

router = APIRouter(prefix="/api/platform/knowledge-graph", tags=["knowledge-graph-integration"])

# The synchronous endpoint is intentionally diagnostic-only. Complete and
# multi-million-row runs belong to the resumable domain-by-domain execution API.
SYNC_DRY_RUN_MAX_ROWS_PER_DOMAIN = 25_000


class ControlledDryRunRequest(BaseModel):
    max_rows_per_domain: int = Field(
        default=10_000,
        ge=1,
        le=SYNC_DRY_RUN_MAX_ROWS_PER_DOMAIN,
        description=(
            "Diagnostic ceiling for the legacy synchronous route. Use the "
            "resumable dry-run API for complete or large-domain validation."
        ),
    )
    batch_size: int = Field(default=500, ge=1, le=2_000)


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Knowledge Graph database not configured")
    return dsn


def _live_inventory(dsn: str) -> tuple[dict, list[DomainInventory]]:
    try:
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                inventory = inventory_full_graph(cur)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to inventory live Knowledge Graph sources") from exc
    objects = [DomainInventory(**item) for item in inventory.get("domains", [])]
    return inventory, objects


def _projection_state(objects: list[DomainInventory]):
    plans = [build_projection(item) for item in objects]
    report = {
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
            for plan in plans
        ],
        "ready_domains": [plan.domain for plan in plans if plan.executable],
        "blocked_domains": [plan.domain for plan in plans if plan.state == "blocked"],
        "unavailable_domains": [plan.domain for plan in plans if plan.state == "unavailable"],
        "withheld_domains": [plan.domain for plan in plans if plan.state == "withheld"],
    }
    return plans, report


@router.get("/full-integration")
def full_graph_integration_inventory():
    dsn = _dsn()
    inventory, objects = _live_inventory(dsn)
    plans, projection_report = _projection_state(objects)
    unresolved = unresolved_queue_report(queue_from_projection_plans(plans))

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


@router.post("/controlled-dry-run", dependencies=[Depends(verify_owner_or_api_key)])
def controlled_graph_dry_run(request: ControlledDryRunRequest):
    """Run a bounded diagnostic dry run; never persist graph writes.

    This legacy synchronous route is deliberately capped. Complete validation,
    especially media-scale validation, must use the resumable execution API so
    proxy disconnects or request timeouts cannot leave an unbounded task running.
    """
    dsn = _dsn()
    inventory, objects = _live_inventory(dsn)
    plans, projection_report = _projection_state(objects)

    queries = dict(enabled_queries())
    for plan in plans:
        if plan.executable and plan.sql:
            queries[plan.domain] = plan.sql

    adapter_map = adapters_by_domain()
    adapters = tuple(adapter_map[d] for d in queries if d in adapter_map)
    unresolved = unresolved_queue_report(queue_from_projection_plans(plans))

    report = run_controlled_dry_run(
        PostgresGraphRepository(dsn),
        PostgresSourceProvider(dsn, queries),
        adapters=adapters,
        max_rows_per_domain=request.max_rows_per_domain,
        batch_size=request.batch_size,
    )

    missing_adapter_domains = sorted(d for d in projection_report["ready_domains"] if d not in adapter_map)
    projection_blockers = [
        *(f"projection_blocked:{d}" for d in projection_report["blocked_domains"]),
        *(f"source_unavailable:{d}" for d in projection_report["unavailable_domains"]),
        *(f"adapter_missing:{d}" for d in missing_adapter_domains),
    ]
    if unresolved["publication_blocked"]:
        projection_blockers.append(f"unresolved_taxon_items:{unresolved['total_items']}")

    if projection_blockers:
        report["publication_authorization_ready"] = False
        report.setdefault("errors", []).extend(projection_blockers)

    authorization = publication_authorization_payload(report)
    authorization["inventory_contract"] = inventory.get("contract")
    authorization["projection_contract"] = projection_report.get("contract")
    authorization["unresolved_queue_contract"] = unresolved.get("contract")
    authorization["operator_command"] = (
        "POST /api/platform/knowledge-graph/controlled-dry-run for a bounded diagnostic; "
        "use the resumable dry-run API for complete validation; production publication "
        "remains a separate explicitly authorized operation."
    )
    authorization["rollback_note"] = (
        "No rollback is required for this dry run because all generated nodes and edges exist only in memory."
    )

    return {
        "dry_run": report,
        "authorization": authorization,
        "source_projections": projection_report,
        "unresolved_taxon_queue": unresolved,
        "synchronous_row_ceiling_per_domain": SYNC_DRY_RUN_MAX_ROWS_PER_DOMAIN,
        "resumable_execution_required_for_complete_run": True,
        "production_write_executed": False,
    }


@router.get("/persisted-audit", dependencies=[Depends(verify_owner_or_api_key)])
def persisted_knowledge_graph_audit():
    """Read-only integrity and coverage audit of the persisted graph."""
    dsn = _dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                return persisted_graph_audit(cur)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to audit persisted Knowledge Graph") from exc
