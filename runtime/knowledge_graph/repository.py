"""Read/write access to the graph store, behind a small interface.

The interface is deliberately thin so that:

* production traversal uses :class:`PostgresGraphRepository` against the live
  ``oc_graph.kg_nodes`` / ``oc_graph.kg_edges`` tables (read-only paths only);
* tests use :class:`InMemoryGraphRepository`, which never opens a database
  connection — guaranteeing "no production writes during tests".

Only the ``write_*`` methods mutate anything, and they are used exclusively by
the publisher during an explicit build run.  The API router only ever calls
read methods.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Protocol

from .models import Edge, Node

_NODE_COLUMNS = (
    "kg_node_id, node_type, canonical_key, display_label, source_table, "
    "source_pk, evidence_class, confidence_score, confidence_label, payload_json"
)
_EDGE_COLUMNS = (
    "kg_edge_id, edge_type, from_node_id, to_node_id, source_table, source_pk, "
    "evidence_class, confidence_score, confidence_label, rule_name, payload_json"
)


def _as_payload(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {}


class GraphRepository(Protocol):
    def get_node(self, node_id: int) -> Node | None: ...
    def get_node_by_key(self, canonical_key: str) -> Node | None: ...
    def find_genus_node(self, genus_name: str) -> Node | None: ...
    def get_nodes(self, node_ids: Iterable[int]) -> list[Node]: ...
    def get_outgoing_edges(
        self,
        node_ids: Iterable[int],
        edge_types: Iterable[str] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Edge]: ...
    def all_nodes(self) -> list[Node]: ...
    def all_edges(self) -> list[Edge]: ...


class InMemoryGraphRepository:
    """A pure-Python graph store for tests and offline validation."""

    def __init__(self, nodes: list[Node] | None = None, edges: list[Edge] | None = None):
        self._nodes: dict[int, Node] = {n.kg_node_id: n for n in (nodes or [])}
        self._edges: list[Edge] = list(edges or [])
        self._next_node_id = (max(self._nodes) + 1) if self._nodes else 1
        self._next_edge_id = (max((e.kg_edge_id for e in self._edges), default=0) + 1)

    # ---- read ----
    def get_node(self, node_id: int) -> Node | None:
        return self._nodes.get(node_id)

    def get_node_by_key(self, canonical_key: str) -> Node | None:
        for n in self._nodes.values():
            if n.canonical_key == canonical_key:
                return n
        return None

    def find_genus_node(self, genus_name: str) -> Node | None:
        target = genus_name.strip().lower()
        for n in self._nodes.values():
            if n.node_type == "genus" and (n.display_label or "").strip().lower() == target:
                return n
        return None

    def get_nodes(self, node_ids: Iterable[int]) -> list[Node]:
        return [self._nodes[i] for i in node_ids if i in self._nodes]

    def get_outgoing_edges(self, node_ids, edge_types=None, limit=100, offset=0):
        ids = set(node_ids)
        types = set(edge_types) if edge_types else None
        out = [
            e for e in self._edges
            if e.from_node_id in ids and (types is None or e.edge_type in types)
        ]
        out.sort(key=lambda e: e.kg_edge_id)
        return out[offset: offset + limit]

    def all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def all_edges(self) -> list[Edge]:
        return list(self._edges)

    # ---- write (idempotent, keyed on canonical identity) ----
    def upsert_node(self, node: Node) -> Node:
        existing = self.get_node_by_key(node.canonical_key)
        if existing is not None:
            merged = Node(
                kg_node_id=existing.kg_node_id,
                node_type=node.node_type,
                canonical_key=node.canonical_key,
                display_label=node.display_label,
                source_table=node.source_table,
                source_pk=node.source_pk,
                evidence_class=node.evidence_class,
                confidence_score=node.confidence_score,
                confidence_label=node.confidence_label,
                payload=node.payload,
            )
            self._nodes[existing.kg_node_id] = merged
            return merged
        new = Node(
            kg_node_id=self._next_node_id,
            node_type=node.node_type,
            canonical_key=node.canonical_key,
            display_label=node.display_label,
            source_table=node.source_table,
            source_pk=node.source_pk,
            evidence_class=node.evidence_class,
            confidence_score=node.confidence_score,
            confidence_label=node.confidence_label,
            payload=node.payload,
        )
        self._nodes[new.kg_node_id] = new
        self._next_node_id += 1
        return new

    def upsert_edge(self, edge: Edge) -> Edge:
        for e in self._edges:
            if (
                e.edge_type == edge.edge_type
                and e.from_node_id == edge.from_node_id
                and e.to_node_id == edge.to_node_id
                and e.source_table == edge.source_table
            ):
                return e
        new = Edge(
            kg_edge_id=self._next_edge_id,
            edge_type=edge.edge_type,
            from_node_id=edge.from_node_id,
            to_node_id=edge.to_node_id,
            source_table=edge.source_table,
            source_pk=edge.source_pk,
            evidence_class=edge.evidence_class,
            confidence_score=edge.confidence_score,
            confidence_label=edge.confidence_label,
            rule_name=edge.rule_name,
            payload=edge.payload,
        )
        self._edges.append(new)
        self._next_edge_id += 1
        return new


class PostgresGraphRepository:
    """Read-only traversal over the live ``oc_graph`` tables via psycopg."""

    def __init__(self, dsn: str, schema: str = "oc_graph"):
        self._dsn = dsn
        self._schema = schema

    def _connect(self):
        import psycopg  # imported lazily so tests never require a driver/DB
        return psycopg.connect(self._dsn, connect_timeout=5)

    def _row_to_node(self, row: tuple) -> Node:
        return Node(
            kg_node_id=row[0], node_type=row[1], canonical_key=row[2],
            display_label=row[3], source_table=row[4], source_pk=row[5],
            evidence_class=row[6], confidence_score=(float(row[7]) if row[7] is not None else None),
            confidence_label=row[8], payload=_as_payload(row[9]),
        )

    def _row_to_edge(self, row: tuple) -> Edge:
        return Edge(
            kg_edge_id=row[0], edge_type=row[1], from_node_id=row[2], to_node_id=row[3],
            source_table=row[4], source_pk=row[5], evidence_class=row[6],
            confidence_score=(float(row[7]) if row[7] is not None else None),
            confidence_label=row[8], rule_name=row[9], payload=_as_payload(row[10]),
        )

    def _node_sql(self, where: str) -> str:
        return (
            f"SELECT {_NODE_COLUMNS} FROM {self._schema}.kg_nodes "
            f"WHERE is_active AND {where}"
        )

    def get_node(self, node_id: int) -> Node | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._node_sql("kg_node_id = %s"), (node_id,))
            row = cur.fetchone()
            return self._row_to_node(row) if row else None

    def get_node_by_key(self, canonical_key: str) -> Node | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._node_sql("canonical_key = %s"), (canonical_key,))
            row = cur.fetchone()
            return self._row_to_node(row) if row else None

    def find_genus_node(self, genus_name: str) -> Node | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                self._node_sql("node_type = 'genus' AND lower(display_label) = lower(%s)")
                + " LIMIT 1",
                (genus_name.strip(),),
            )
            row = cur.fetchone()
            return self._row_to_node(row) if row else None

    def get_nodes(self, node_ids: Iterable[int]) -> list[Node]:
        ids = list(node_ids)
        if not ids:
            return []
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._node_sql("kg_node_id = ANY(%s)"), (ids,))
            return [self._row_to_node(r) for r in cur.fetchall()]

    def get_outgoing_edges(self, node_ids, edge_types=None, limit=100, offset=0):
        ids = list(node_ids)
        if not ids:
            return []
        clauses = ["is_active", "from_node_id = ANY(%s)"]
        params: list[Any] = [ids]
        if edge_types:
            clauses.append("edge_type = ANY(%s)")
            params.append(list(edge_types))
        params.extend([limit, offset])
        sql = (
            f"SELECT {_EDGE_COLUMNS} FROM {self._schema}.kg_edges "
            f"WHERE {' AND '.join(clauses)} ORDER BY kg_edge_id LIMIT %s OFFSET %s"
        )
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(sql, params)
            return [self._row_to_edge(r) for r in cur.fetchall()]

    def all_nodes(self) -> list[Node]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._node_sql("TRUE"))
            return [self._row_to_node(r) for r in cur.fetchall()]

    def all_edges(self) -> list[Edge]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT {_EDGE_COLUMNS} FROM {self._schema}.kg_edges WHERE is_active"
            )
            return [self._row_to_edge(r) for r in cur.fetchall()]
