"""Canonical scientific Knowledge Graph traversal and integration API.

Traversal responses are assembled from ``oc_graph.kg_nodes`` and
``oc_graph.kg_edges``. Integration inventory and resumable dry-run operations
are exposed through a separate platform router mounted by this aggregate.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from fastapi import APIRouter, HTTPException, Query

from app.routers.full_graph_integration import router as platform_graph_router
from runtime.knowledge_graph import (
    PostgresGraphRepository,
    canonical_key,
    quality_report,
    traverse,
)
from runtime.knowledge_graph.full_integration import build_publication_plan, inventory_full_graph
from runtime.knowledge_graph.traversal import DEFAULT_LIMIT, MAX_DEPTH, MAX_LIMIT

traversal_router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])


def _dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Knowledge Graph database not configured")
    return dsn


def _repo() -> PostgresGraphRepository:
    return PostgresGraphRepository(_dsn())


def _csv(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def _traverse_response(focal, depth, node_types, edge_types, limit, offset):
    repo = _repo()
    node = focal(repo)
    if node is None:
        raise HTTPException(status_code=404, detail="Node not found in graph")
    return traverse(
        repo, node, depth=depth,
        node_types=_csv(node_types), edge_types=_csv(edge_types),
        limit=limit, offset=offset,
    )


@traversal_router.get("/node/{node_id}")
def get_node(
    node_id: int,
    depth: int = Query(1, ge=1, le=MAX_DEPTH),
    node_types: str | None = None,
    edge_types: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _traverse_response(
        lambda r: r.get_node(node_id), depth, node_types, edge_types, limit, offset
    )


@traversal_router.get("/taxon/{taxon_id}")
def get_taxon(
    taxon_id: str,
    depth: int = Query(1, ge=1, le=MAX_DEPTH),
    node_types: str | None = None,
    edge_types: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    key = taxon_id if ":" in taxon_id else canonical_key("taxon", taxon_id)
    return _traverse_response(
        lambda r: r.get_node_by_key(key), depth, node_types, edge_types, limit, offset
    )


@traversal_router.get("/genus/{genus_name}")
def get_genus(
    genus_name: str,
    depth: int = Query(1, ge=1, le=MAX_DEPTH),
    node_types: str | None = None,
    edge_types: str | None = None,
    limit: int = Query(DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return _traverse_response(
        lambda r: r.find_genus_node(genus_name), depth, node_types, edge_types, limit, offset
    )


@traversal_router.get("/quality")
def graph_quality() -> dict[str, Any]:
    return quality_report(_repo())


@traversal_router.get("/full-integration")
def full_graph_integration() -> dict[str, Any]:
    """Inventory every configured graph domain and return a gated publication plan.

    This endpoint never writes graph nodes or edges. A production publication
    run remains a separately authorized operation.
    """
    try:
        with psycopg.connect(_dsn(), connect_timeout=8) as conn:
            with conn.cursor() as cur:
                inventory = inventory_full_graph(cur)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Unable to inventory live Knowledge Graph sources") from exc
    return {
        "inventory": inventory,
        "publication_plan": build_publication_plan(inventory),
        "warning": "Read-only inventory; no nodes or edges were materialized.",
    }


# app.main already mounts ``knowledge_graph.router``. Keep this aggregate router
# prefix-free so both public prefixes remain unchanged and reachable.
router = APIRouter()
router.include_router(traversal_router)
router.include_router(platform_graph_router)
