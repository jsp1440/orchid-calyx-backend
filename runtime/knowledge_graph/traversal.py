"""Graph traversal service.

Traversal answers: "starting from a focal node, what canonical nodes is it
connected to, over which edges?"  The result is assembled *from graph nodes and
edges* — never from unrelated direct table aggregation — and always reports
domain coverage plus the explicit list of scientific domains that have no data
yet for this focal node.
"""

from __future__ import annotations

from typing import Any, Iterable

from .models import Edge, Node
from .repository import GraphRepository
from .vocabulary import (
    ALL_DOMAINS,
    domain_for_edge_type,
    domain_for_node_type,
)

MAX_DEPTH = 3
MAX_LIMIT = 500
DEFAULT_LIMIT = 100


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def traverse(
    repo: GraphRepository,
    focal: Node,
    depth: int = 1,
    node_types: Iterable[str] | None = None,
    edge_types: Iterable[str] | None = None,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict[str, Any]:
    depth = _clamp(depth, 1, MAX_DEPTH)
    limit = _clamp(limit, 1, MAX_LIMIT)
    offset = max(0, offset)
    requested_offset = offset
    node_type_filter = set(node_types) if node_types else None
    edge_type_filter = set(edge_types) if edge_types else None

    visited_nodes: dict[int, Node] = {focal.kg_node_id: focal}
    collected_edges: dict[int, Edge] = {}
    frontier = [focal.kg_node_id]
    truncated = False

    for _ in range(depth):
        if not frontier:
            break
        edges = repo.get_outgoing_edges(
            frontier,
            edge_types=edge_type_filter,
            limit=limit + 1,
            offset=offset,
        )
        if len(edges) > limit:
            truncated = True
            edges = edges[:limit]

        next_ids: list[int] = []
        target_ids = [e.to_node_id for e in edges if e.to_node_id not in visited_nodes]
        fetched = {n.kg_node_id: n for n in repo.get_nodes(target_ids)}

        for edge in edges:
            target = visited_nodes.get(edge.to_node_id) or fetched.get(edge.to_node_id)
            if target is None:
                continue  # dangling edge — omitted from traversal, flagged by quality checks
            if node_type_filter and target.node_type not in node_type_filter:
                continue
            collected_edges[edge.kg_edge_id] = edge
            if edge.to_node_id not in visited_nodes:
                visited_nodes[edge.to_node_id] = target
                next_ids.append(edge.to_node_id)
        frontier = next_ids
        offset = 0  # offset only applies to the first hop's page

    connected = [n for n in visited_nodes.values() if n.kg_node_id != focal.kg_node_id]
    coverage = _domain_coverage(connected, list(collected_edges.values()))

    return {
        "focal_node": focal.to_dict(),
        "nodes": [n.to_dict() for n in connected],
        "edges": [e.to_dict() for e in collected_edges.values()],
        "node_types": sorted({n.node_type for n in connected}),
        "edge_types": sorted({e.edge_type for e in collected_edges.values()}),
        "domain_coverage": coverage["present"],
        "data_gaps": coverage["gaps"],
        "graph": {
            "depth": depth,
            "node_count": len(connected),
            "edge_count": len(collected_edges),
        },
        "pagination": {
            "limit": limit,
            "offset": requested_offset,
            "truncated": truncated,
            "next_offset": (requested_offset + limit) if truncated else None,
        },
        "filters": {
            "node_types": sorted(node_type_filter) if node_type_filter else None,
            "edge_types": sorted(edge_type_filter) if edge_type_filter else None,
        },
    }


def _domain_coverage(nodes: list[Node], edges: list[Edge]) -> dict[str, Any]:
    present: dict[str, dict[str, int]] = {}
    for n in nodes:
        d = domain_for_node_type(n.node_type)
        present.setdefault(d, {"nodes": 0, "edges": 0})["nodes"] += 1
    for e in edges:
        d = domain_for_edge_type(e.edge_type)
        present.setdefault(d, {"nodes": 0, "edges": 0})["edges"] += 1
    present.pop("unknown", None)
    gaps = [d for d in ALL_DOMAINS if d not in present]
    return {"present": present, "gaps": gaps}
