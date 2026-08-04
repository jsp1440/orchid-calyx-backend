"""Full Knowledge Graph inventory, staged dry runs, and persisted audit routes."""
from __future__ import annotations

import os
from pathlib import Path

import psycopg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.knowledge_graph.adapters import adapters_by_domain
from runtime.knowledge_graph.controlled_dry_run import publication_authorization_payload, run_controlled_dry_run
from runtime.knowledge_graph.dynamic_source_projection import build_projection
from runtime.knowledge_graph.full_domain_status import full_domain_code_readiness
from runtime.knowledge_graph.full_integration import DomainInventory, build_publication_plan, inventory_full_graph
from runtime.knowledge_graph.post_publication_audit import persisted_graph_audit
from runtime.knowledge_graph.repository import PostgresGraphRepository
from runtime.knowledge_graph.resumable_dry_run import JsonSessionStore
from runtime.knowledge_graph.resumable_executor import create_session, resume_session, session_report
from runtime.knowledge_graph.source_registry import enabled_queries
from runtime.knowledge_graph.sources import PostgresSourceProvider
from runtime.knowledge_graph.unresolved_taxon_queue import queue_from_projection_plans, unresolved_queue_report

router = APIRouter(prefix="/api/platform/knowledge-graph", tags=["knowledge-graph-integration"])
SYNC_DRY_RUN_MAX_ROWS_PER_DOMAIN = 25_000


class ControlledDryRunRequest(BaseModel):
    max_rows_per_domain: int = Field(default=10_000, ge=1, le=SYNC_DRY_RUN_MAX_ROWS_PER_DOMAIN)
    batch_size: int = Field(default=500, ge=1, le=2_000)


class ResumableDryRunRequest(BaseModel):
    domains: list[str] = Field(min_length=1, max_length=16)
    batch_size: int = Field(default=1_000, ge=1, le=5_000)
    max_batches_per_step: int = Field(default=5, ge=1, le=25)


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Knowledge Graph database not configured")
    return dsn


def _dry_run_root() -> Path:
    root = Path(os.getenv("CALYX_DRY_RUN_DIRECTORY", "/tmp/calyx-graph-dry-runs"))
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_store() -> JsonSessionStore:
    return JsonSessionStore(str(_dry_run_root() / "sessions"))


def _live_inventory(dsn: str) -> tuple[dict, list[DomainInventory]]:
    try:
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                inventory = inventory_full_graph(cur)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to inventory live Knowledge Graph sources") from exc
    return inventory, [DomainInventory(**item) for item in inventory.get("domains", [])]


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


def _live_execution_dependencies(dsn: str):
    _inventory, objects = _live_inventory(dsn)
    plans, projection_report = _projection_state(objects)
    queries = dict(enabled_queries())
    for plan in plans:
        if plan.executable and plan.sql:
            queries[plan.domain] = plan.sql
    adapter_map = adapters_by_domain()
    allowed = set(queries).intersection(adapter_map)
    return plans, projection_report, queries, adapter_map, allowed


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
    blockers = [
        *(f"projection_blocked:{d}" for d in projection_report["blocked_domains"]),
        *(f"source_unavailable:{d}" for d in projection_report["unavailable_domains"]),
        *(f"adapter_missing:{d}" for d in missing_adapter_domains),
    ]
    if unresolved["publication_blocked"]:
        blockers.append(f"unresolved_taxon_items:{unresolved['total_items']}")
    if blockers:
        report["publication_authorization_ready"] = False
        report.setdefault("errors", []).extend(blockers)
    authorization = publication_authorization_payload(report)
    authorization["inventory_contract"] = inventory.get("contract")
    authorization["operator_command"] = "Use POST /dry-runs for complete validation; production publication remains separate."
    return {
        "dry_run": report,
        "authorization": authorization,
        "source_projections": projection_report,
        "unresolved_taxon_queue": unresolved,
        "synchronous_row_ceiling_per_domain": SYNC_DRY_RUN_MAX_ROWS_PER_DOMAIN,
        "resumable_execution_required_for_complete_run": True,
        "production_write_executed": False,
    }


@router.post("/dry-runs", dependencies=[Depends(verify_owner_or_api_key)])
def start_resumable_dry_run(request: ResumableDryRunRequest):
    dsn = _dsn()
    plans, projection_report, _queries, _adapters, allowed = _live_execution_dependencies(dsn)
    try:
        session = create_session(
            _session_store(),
            domains=request.domains,
            allowed_domains=allowed,
            batch_size=request.batch_size,
            max_batches_per_step=request.max_batches_per_step,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "contract": "calyx-resumable-graph-dry-run-v1",
        "session": session.to_dict(),
        "allowed_domains": sorted(allowed),
        "blocked_domains": projection_report["blocked_domains"],
        "unavailable_domains": projection_report["unavailable_domains"],
        "unresolved_taxon_queue": unresolved_queue_report(queue_from_projection_plans(plans)),
        "next_action": f"POST /api/platform/knowledge-graph/dry-runs/{session.run_id}/resume",
        "production_graph_mutation": False,
    }


@router.get("/dry-runs/{run_id}", dependencies=[Depends(verify_owner_or_api_key)])
def get_resumable_dry_run(run_id: str):
    session = _session_store().load(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dry-run session not found")
    return session_report(session, str(_dry_run_root() / "staging"))


@router.post("/dry-runs/{run_id}/resume", dependencies=[Depends(verify_owner_or_api_key)])
def resume_resumable_dry_run(run_id: str):
    dsn = _dsn()
    _plans, _projection_report, queries, adapter_map, _allowed = _live_execution_dependencies(dsn)
    try:
        return resume_session(
            _session_store(),
            str(_dry_run_root() / "staging"),
            PostgresGraphRepository(dsn),
            PostgresSourceProvider(dsn, queries),
            adapter_map,
            run_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Dry-run session not found") from exc


@router.post("/dry-runs/{run_id}/cancel", dependencies=[Depends(verify_owner_or_api_key)])
def cancel_resumable_dry_run(run_id: str):
    session = _session_store().cancel(run_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Dry-run session not found")
    return session_report(session, str(_dry_run_root() / "staging"))


@router.get("/persisted-audit", dependencies=[Depends(verify_owner_or_api_key)])
def persisted_knowledge_graph_audit():
    dsn = _dsn()
    try:
        with psycopg.connect(dsn, connect_timeout=8) as conn:
            with conn.cursor() as cur:
                return persisted_graph_audit(cur)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to audit persisted Knowledge Graph") from exc
