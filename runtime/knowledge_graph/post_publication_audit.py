"""Read-only audit of the persisted Knowledge Graph after a publication run."""

from __future__ import annotations

from typing import Any


def persisted_graph_audit(cur) -> dict[str, Any]:
    """Measure persisted nodes, edges, integrity, duplicates, and domain coverage.

    This function issues SELECT statements only.  It is safe to run before or
    after publication and never repairs or mutates the graph.
    """
    cur.execute("SELECT COUNT(*) FROM oc_graph.kg_nodes")
    total_nodes = int(cur.fetchone()[0])
    cur.execute("SELECT COUNT(*) FROM oc_graph.kg_edges")
    total_edges = int(cur.fetchone()[0])

    cur.execute(
        """
        SELECT node_type, COUNT(*) AS records, COUNT(DISTINCT canonical_key) AS identities
        FROM oc_graph.kg_nodes
        GROUP BY node_type
        ORDER BY node_type
        """
    )
    nodes_by_type = [
        {"node_type": row[0], "records": int(row[1]), "identities": int(row[2])}
        for row in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT edge_type, COUNT(*) AS records,
               COUNT(DISTINCT from_node_id) AS source_nodes,
               COUNT(DISTINCT to_node_id) AS target_nodes
        FROM oc_graph.kg_edges
        GROUP BY edge_type
        ORDER BY edge_type
        """
    )
    edges_by_type = [
        {
            "edge_type": row[0],
            "records": int(row[1]),
            "source_nodes": int(row[2]),
            "target_nodes": int(row[3]),
        }
        for row in cur.fetchall()
    ]

    cur.execute(
        """
        SELECT COUNT(*)
        FROM oc_graph.kg_edges e
        LEFT JOIN oc_graph.kg_nodes f ON f.kg_node_id = e.from_node_id
        LEFT JOIN oc_graph.kg_nodes t ON t.kg_node_id = e.to_node_id
        WHERE f.kg_node_id IS NULL OR t.kg_node_id IS NULL
        """
    )
    orphan_edges = int(cur.fetchone()[0])

    cur.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT canonical_key
          FROM oc_graph.kg_nodes
          GROUP BY canonical_key
          HAVING COUNT(*) > 1
        ) d
        """
    )
    duplicate_node_keys = int(cur.fetchone()[0])

    cur.execute(
        """
        SELECT COUNT(*) FROM (
          SELECT edge_type, from_node_id, to_node_id, COALESCE(source_pk, '')
          FROM oc_graph.kg_edges
          GROUP BY edge_type, from_node_id, to_node_id, COALESCE(source_pk, '')
          HAVING COUNT(*) > 1
        ) d
        """
    )
    duplicate_edges = int(cur.fetchone()[0])

    healthy = orphan_edges == 0 and duplicate_node_keys == 0 and duplicate_edges == 0
    return {
        "contract": "calyx-persisted-graph-audit-v1",
        "graph_mutation": False,
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "nodes_by_type": nodes_by_type,
        "edges_by_type": edges_by_type,
        "orphan_edges": orphan_edges,
        "duplicate_node_keys": duplicate_node_keys,
        "duplicate_edges": duplicate_edges,
        "healthy": healthy,
        "blockers": [
            *([f"orphan_edges:{orphan_edges}"] if orphan_edges else []),
            *([f"duplicate_node_keys:{duplicate_node_keys}"] if duplicate_node_keys else []),
            *([f"duplicate_edges:{duplicate_edges}"] if duplicate_edges else []),
        ],
    }
