"""Read-only graph-quality metrics.

These checks never mutate the graph.  They surface structural integrity
problems (orphans, dangling edges, duplicate canonical nodes, missing
provenance, invalid vocabulary) so Mission Control can display real state
rather than an invented completion percentage.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from .repository import GraphRepository
from .vocabulary import EDGE_TYPE_DOMAIN, NODE_TYPE_DOMAIN


def quality_report(repo: GraphRepository) -> dict[str, Any]:
    nodes = repo.all_nodes()
    edges = repo.all_edges()
    node_ids = {n.kg_node_id for n in nodes}

    referenced: set[int] = set()
    dangling_edges = 0
    for e in edges:
        referenced.add(e.from_node_id)
        referenced.add(e.to_node_id)
        if e.from_node_id not in node_ids or e.to_node_id not in node_ids:
            dangling_edges += 1

    orphan_nodes = sum(1 for n in nodes if n.kg_node_id not in referenced)

    key_counts = Counter(n.canonical_key for n in nodes)
    duplicate_canonical = sum(c - 1 for c in key_counts.values() if c > 1)

    missing_provenance = sum(
        1 for n in nodes if not n.source_table or not n.source_pk
    )
    invalid_node_types = sorted(
        {n.node_type for n in nodes if n.node_type not in NODE_TYPE_DOMAIN}
    )
    invalid_edge_types = sorted(
        {e.edge_type for e in edges if e.edge_type not in EDGE_TYPE_DOMAIN}
    )

    issues = (
        dangling_edges
        + orphan_nodes
        + duplicate_canonical
        + missing_provenance
        + len(invalid_node_types)
        + len(invalid_edge_types)
    )

    return {
        "node_count": len(nodes),
        "edge_count": len(edges),
        "orphan_nodes": orphan_nodes,
        "dangling_edges": dangling_edges,
        "duplicate_canonical_nodes": duplicate_canonical,
        "missing_provenance": missing_provenance,
        "invalid_node_types": invalid_node_types,
        "invalid_edge_types": invalid_edge_types,
        "total_issues": issues,
        "healthy": issues == 0,
    }
