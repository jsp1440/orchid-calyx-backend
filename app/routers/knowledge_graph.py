"""Canonical scientific Knowledge Graph traversal API.

All responses are assembled *from graph nodes and edges* (``oc_graph.kg_nodes``
/ ``oc_graph.kg_edges``) via the traversal service — never from unrelated direct
table aggregation.  Every route is read-only.

Endpoints:
  GET /api/knowledge-graph/node/{node_id}
  GET /api/knowledge-graph/taxon/{taxon_id}
  GET /api/knowledge-graph/genus/{genus_name}
  GET /api/knowledge-graph/quality
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException, Query

from runtime.knowledge_graph import (
    PostgresGraphRepository,
    canonical_key,
    quality_report,
    traverse,
)
from runtime.knowledge_graph.traversal import DEFAULT_LIMIT, MAX_DEPTH, MAX_LIMIT

router = APIRouter(prefix="/api/knowledge-graph", tags=["knowledge-graph"])


def _repo() -> PostgresGraphRepository:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise HTTPException(status_code=503, detail="Knowledge Graph database not configured")
    return PostgresGraphRepository(dsn)


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


@router.get("/node/{node_id}")
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


@router.get("/taxon/{taxon_id}")
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


@router.get("/genus/{genus_name}")
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


@router.get("/quality")
def graph_quality() -> dict[str, Any]:
    return quality_report(_repo())
