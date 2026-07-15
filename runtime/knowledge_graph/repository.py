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
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Iterable, Protocol

from .models import Edge, Node


def _json_default(o: Any):
    """JSON encoder fallback for payloads sourced from Postgres.

    ``kg_nodes.payload_json`` / ``kg_edges.payload_json`` are jsonb.  Source
    rows may carry ``Decimal`` (numeric columns) and ``date``/``datetime``
    values that ``json.dumps`` cannot serialize by default.  Decimals become
    JSON numbers (int when integral, else float); temporals become ISO strings.
    """
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")

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
        # O(1) lookup indexes (identity is stable, so these stay valid across
        # idempotent upserts). Without them, bulk population is O(n^2).
        self._key_index: dict[str, int] = {
            n.canonical_key: n.kg_node_id for n in self._nodes.values()
        }
        self._edge_index: set[tuple[Any, Any, Any, Any]] = {
            (e.edge_type, e.from_node_id, e.to_node_id, e.source_table)
            for e in self._edges
        }

    # ---- read ----
    def get_node(self, node_id: int) -> Node | None:
        return self._nodes.get(node_id)

    def get_node_by_key(self, canonical_key: str) -> Node | None:
        node_id = self._key_index.get(canonical_key)
        return self._nodes.get(node_id) if node_id is not None else None

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
        self._key_index[new.canonical_key] = new.kg_node_id
        self._next_node_id += 1
        return new

    def upsert_edge(self, edge: Edge) -> Edge:
        dedup = (edge.edge_type, edge.from_node_id, edge.to_node_id, edge.source_table)
        if dedup in self._edge_index:
            for e in self._edges:
                if (e.edge_type, e.from_node_id, e.to_node_id, e.source_table) == dedup:
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
        self._edge_index.add(dedup)
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

    def taxonomy_nodes(self) -> list[Node]:
        """Only ``taxon``/``genus`` nodes — the backbone needed to seed a staging
        graph.  Avoids streaming the entire production graph via ``all_nodes``.
        """
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(self._node_sql("node_type IN ('taxon','genus')"))
            return [self._row_to_node(r) for r in cur.fetchall()]


class _LazyEdgeView:
    """A read-only sequence of edges whose ``len()`` is an O(1) cached count.

    The frozen publisher measures ``len(repo.all_edges())`` before and after
    every :meth:`upsert_edge` to decide whether a row was written.  Streaming
    the whole ``kg_edges`` table twice per edge would be O(n^2); instead the
    writable repository maintains a live active-edge counter and hands the
    publisher this view.  Iteration (used only by validation/quality/reporting,
    once per domain) lazily loads the real rows on demand.
    """

    __slots__ = ("_count", "_loader", "_cache")

    def __init__(self, count: int, loader: "Callable[[], list[Edge]]"):
        self._count = count
        self._loader = loader
        self._cache: list[Edge] | None = None

    def _rows(self) -> list[Edge]:
        if self._cache is None:
            self._cache = self._loader()
        return self._cache

    def __len__(self) -> int:
        return self._count

    def __iter__(self):
        return iter(self._rows())

    def __getitem__(self, index):
        return self._rows()[index]


class WritablePostgresGraphRepository(PostgresGraphRepository):
    """Production-writable graph store satisfying the same upsert contract as
    :class:`InMemoryGraphRepository`.

    The frozen publisher/orchestrator write to this repository or to the
    in-memory one interchangeably — it exposes ``upsert_node``/``upsert_edge``/
    ``get_node_by_key`` with identical semantics.

    Persistence:

    * **Nodes** — ``INSERT ... ON CONFLICT (node_type, canonical_key) DO UPDATE``
      against the existing ``kg_nodes_unique`` index.  ``created_at`` is never
      touched on update, preserving provenance timestamps; identity is never
      redesigned.
    * **Edges** — ``kg_edges`` has no unique constraint (and we must not add
      one), so idempotency uses ``INSERT ... WHERE NOT EXISTS`` on the existing
      logical identity ``(edge_type, from_node_id, to_node_id, source_table)``.

    Transactions:  a single persistent connection with autocommit disabled.  By
    default the *entire run* commits once (via :meth:`commit`/context-manager
    exit) or rolls back as a unit — no partial batches are ever committed.  An
    optional ``commit_every`` enables incremental commits for very large runs;
    idempotent writes make a subsequent RESUME converge to identical contents.
    """

    def __init__(
        self,
        dsn: str,
        schema: str = "oc_graph",
        *,
        build_run_id: int | None = None,
        commit_every: int | None = None,
    ):
        super().__init__(dsn, schema)
        self._build_run_id = build_run_id
        self._commit_every = commit_every
        self._conn: Any = None
        self._edge_count: int | None = None
        self._edge_ids: dict | None = None  # identity (edge_type,from,to,source_table) -> kg_edge_id
        self._ops_since_commit = 0
        self._key_cache: dict = {}  # canonical_key -> Node|None (write-through)
        self._cache_complete = False  # True once all active node keys preloaded
        self._node_insert_sql = (
            f"INSERT INTO {self._schema}.kg_nodes "
            "(node_type, canonical_key, display_label, source_table, source_pk, "
            " evidence_class, confidence_score, confidence_label, payload_json, "
            " is_active, build_run_id, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,TRUE,%s,now()) "
            "ON CONFLICT (node_type, canonical_key) DO UPDATE SET "
            " display_label=EXCLUDED.display_label, source_table=EXCLUDED.source_table, "
            " source_pk=EXCLUDED.source_pk, evidence_class=EXCLUDED.evidence_class, "
            " confidence_score=EXCLUDED.confidence_score, "
            " confidence_label=EXCLUDED.confidence_label, "
            " payload_json=EXCLUDED.payload_json, is_active=TRUE, "
            " build_run_id=EXCLUDED.build_run_id, updated_at=now() "
            "RETURNING kg_node_id"
        )
        self._edge_insert_sql = (
            f"INSERT INTO {self._schema}.kg_edges "
            "(edge_type, from_node_id, to_node_id, source_table, source_pk, "
            " evidence_class, confidence_score, confidence_label, rule_name, "
            " payload_json, is_active, build_run_id, updated_at) "
            "SELECT %s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,TRUE,%s,now() "
            f"WHERE NOT EXISTS (SELECT 1 FROM {self._schema}.kg_edges "
            " WHERE edge_type=%s AND from_node_id=%s AND to_node_id=%s "
            "   AND source_table IS NOT DISTINCT FROM %s AND is_active) "
            "RETURNING kg_edge_id"
        )
        self._edge_id_sql = (
            f"SELECT kg_edge_id FROM {self._schema}.kg_edges "
            "WHERE edge_type=%s AND from_node_id=%s AND to_node_id=%s "
            "  AND source_table IS NOT DISTINCT FROM %s AND is_active "
            "ORDER BY kg_edge_id LIMIT 1"
        )
        self._edge_plain_insert_sql = (
            f"INSERT INTO {self._schema}.kg_edges "
            "(edge_type, from_node_id, to_node_id, source_table, source_pk, "
            " evidence_class, confidence_score, confidence_label, rule_name, "
            " payload_json, is_active, build_run_id, updated_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,TRUE,%s,now()) "
            "RETURNING kg_edge_id"
        )

    # ---- connection / transaction management ----
    def _wconn(self):
        if self._conn is None or getattr(self._conn, "closed", False):
            import psycopg  # lazy: tests without a DB never import a driver
            self._conn = psycopg.connect(self._dsn, connect_timeout=10, autocommit=False)
        return self._conn

    def commit(self) -> None:
        if self._conn is not None and not getattr(self._conn, "closed", False):
            self._conn.commit()
        self._ops_since_commit = 0

    def rollback(self) -> None:
        if self._conn is not None and not getattr(self._conn, "closed", False):
            self._conn.rollback()
        self._ops_since_commit = 0
        self._edge_count = None  # cached count is invalid after a rollback
        self._edge_ids = None
        self._key_cache.clear()
        self._cache_complete = False

    def close(self) -> None:
        if self._conn is not None and not getattr(self._conn, "closed", False):
            self._conn.close()
        self._conn = None

    def __enter__(self) -> "WritablePostgresGraphRepository":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        finally:
            self.close()
        return False

    def _maybe_autocommit(self) -> None:
        self._ops_since_commit += 1
        if self._commit_every and self._ops_since_commit >= self._commit_every:
            self.commit()

    # ---- writes (idempotent, keyed on canonical identity) ----
    @staticmethod
    def _node_content_equal(a: Node, b: Node) -> bool:
        return (
            a.node_type == b.node_type
            and a.display_label == b.display_label
            and a.source_table == b.source_table
            and str(a.source_pk) == str(b.source_pk)
            and a.evidence_class == b.evidence_class
            and a.confidence_score == b.confidence_score
            and a.confidence_label == b.confidence_label
            and (a.payload or {}) == (b.payload or {})
        )

    def upsert_node(self, node: Node) -> Node:
        # Idempotent fast path: if the canonical_key already exists with IDENTICAL
        # content (complete cache), re-publishing it is a true no-op, keeping RESUME
        # and idempotency reruns in-memory instead of one DB round-trip per row.
        # If content differs, fall through to ON CONFLICT DO UPDATE (content refresh
        # while preserving created_at), preserving the BUILD-067 update contract.
        if not self._cache_complete and self._has_open_conn():
            self._preload_keys()
        cached = self._key_cache.get(node.canonical_key)
        if cached is not None and self._node_content_equal(cached, node):
            return cached
        conn = self._wconn()
        with conn.cursor() as cur:
            cur.execute(self._node_insert_sql, (
                node.node_type, node.canonical_key, node.display_label,
                node.source_table, node.source_pk, node.evidence_class,
                node.confidence_score, node.confidence_label,
                json.dumps(node.payload or {}, default=_json_default), self._build_run_id,
            ))
            new_id = cur.fetchone()[0]
        self._maybe_autocommit()
        stored = Node(
            kg_node_id=new_id, node_type=node.node_type,
            canonical_key=node.canonical_key, display_label=node.display_label,
            source_table=node.source_table, source_pk=node.source_pk,
            evidence_class=node.evidence_class, confidence_score=node.confidence_score,
            confidence_label=node.confidence_label, payload=node.payload,
        )
        self._key_cache[node.canonical_key] = stored  # write-through
        return stored

    def _ensure_edge_ids(self) -> None:
        """Load active edge logical identities into memory once.

        The publisher deduplicates by ``(edge_type, from_node_id, to_node_id,
        source_table)``.  ``kg_edges`` carries no unique index (schema frozen),
        so an in-memory identity set replaces a per-edge ``WHERE NOT EXISTS``
        table scan.  Single-writer transaction: no other session mutates the
        graph during the run, so the set stays authoritative; duplicates would
        still be caught by ``duplicate_relationships`` in final validation.
        """
        if self._edge_ids is not None:
            return
        conn = self._wconn()
        ids: dict = {}
        n = 0
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT edge_type, from_node_id, to_node_id, source_table, kg_edge_id "
                f"FROM {self._schema}.kg_edges WHERE is_active ORDER BY kg_edge_id"
            )
            for r in cur:
                n += 1
                key = (r[0], r[1], r[2], r[3])
                if key not in ids:  # keep lowest id per identity (matches prior ORDER BY LIMIT 1)
                    ids[key] = r[4]
        self._edge_ids = ids
        if self._edge_count is None:
            self._edge_count = n

    def upsert_edge(self, edge: Edge) -> Edge:
        ev = edge.evidence_class or "normalized"  # kg_edges.evidence_class is NOT NULL; 'normalized' is the graph-wide convention
        self._ensure_edge_ids()
        identity = (edge.edge_type, edge.from_node_id, edge.to_node_id, edge.source_table)
        if identity in self._edge_ids:
            # idempotent no-op; publisher detects the skip via unchanged len(all_edges()).
            # Return the EXISTING edge id (BUILD-067 dedup contract).
            return Edge(
                kg_edge_id=self._edge_ids[identity], edge_type=edge.edge_type,
                from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
                source_table=edge.source_table, source_pk=edge.source_pk,
                evidence_class=ev, confidence_score=edge.confidence_score,
                confidence_label=edge.confidence_label, rule_name=edge.rule_name,
                payload=edge.payload,
            )
        conn = self._wconn()
        with conn.cursor() as cur:
            cur.execute(self._edge_plain_insert_sql, (
                edge.edge_type, edge.from_node_id, edge.to_node_id, edge.source_table,
                edge.source_pk, ev, edge.confidence_score,
                edge.confidence_label, edge.rule_name, json.dumps(edge.payload or {}, default=_json_default),
                self._build_run_id,
            ))
            new_id = cur.fetchone()[0]
        self._edge_ids[identity] = new_id
        if self._edge_count is not None:
            self._edge_count += 1
        self._maybe_autocommit()
        return Edge(
            kg_edge_id=new_id, edge_type=edge.edge_type,
            from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
            source_table=edge.source_table, source_pk=edge.source_pk,
            evidence_class=ev, confidence_score=edge.confidence_score,
            confidence_label=edge.confidence_label, rule_name=edge.rule_name,
            payload=edge.payload,
        )

    # ---- reads (use the open write transaction so validation sees pending
    #      writes; fall back to the parent's short-lived reads when idle) ----
    def _has_open_conn(self) -> bool:
        return self._conn is not None and not getattr(self._conn, "closed", False)

    def get_node(self, node_id: int) -> Node | None:
        if not self._has_open_conn():
            return super().get_node(node_id)
        with self._conn.cursor() as cur:
            cur.execute(self._node_sql("kg_node_id = %s"), (node_id,))
            row = cur.fetchone()
            return self._row_to_node(row) if row else None

    def _preload_keys(self) -> None:
        """Load every active node keyed by canonical_key once.

        After preload a cache miss authoritatively means the node does not
        exist, so the frozen publisher's per-record ``get_node_by_key`` calls
        (taxon resolution + new-node existence checks) become in-memory O(1)
        instead of one DB round-trip each.  Write-through in ``upsert_node``
        keeps the cache complete as new domain nodes are created.
        """
        conn = self._wconn()
        with conn.cursor() as cur:
            cur.execute(self._node_sql("TRUE"))
            for row in cur.fetchall():
                n = self._row_to_node(row)
                self._key_cache[n.canonical_key] = n
        self._cache_complete = True

    def get_node_by_key(self, canonical_key: str) -> Node | None:
        if not self._cache_complete and self._has_open_conn():
            self._preload_keys()
        if canonical_key in self._key_cache:
            return self._key_cache[canonical_key]
        if self._cache_complete:
            return None  # complete cache: a miss means the node does not exist
        if not self._has_open_conn():
            return super().get_node_by_key(canonical_key)
        with self._conn.cursor() as cur:
            cur.execute(self._node_sql("canonical_key = %s"), (canonical_key,))
            row = cur.fetchone()
        result = self._row_to_node(row) if row else None
        self._key_cache[canonical_key] = result
        return result

    def all_nodes(self) -> list[Node]:
        if not self._has_open_conn():
            return super().all_nodes()
        with self._conn.cursor() as cur:
            cur.execute(self._node_sql("TRUE"))
            return [self._row_to_node(r) for r in cur.fetchall()]

    def all_edges(self):
        if not self._has_open_conn():
            return super().all_edges()
        if self._edge_count is None:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT count(*) FROM {self._schema}.kg_edges WHERE is_active"
                )
                self._edge_count = cur.fetchone()[0]

        def _loader() -> list[Edge]:
            with self._conn.cursor() as cur:
                cur.execute(
                    f"SELECT {_EDGE_COLUMNS} FROM {self._schema}.kg_edges WHERE is_active"
                )
                return [self._row_to_edge(r) for r in cur.fetchall()]

        return _LazyEdgeView(self._edge_count, _loader)
