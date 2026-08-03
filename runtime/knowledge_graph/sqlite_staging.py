"""Temporary disk-backed graph used only by resumable dry runs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import Edge, Node


class SqliteStagingGraphRepository:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT NOT NULL, canonical_key TEXT NOT NULL UNIQUE, display_label TEXT, source_table TEXT, source_pk TEXT, evidence_class TEXT, confidence_score REAL, confidence_label TEXT, payload TEXT NOT NULL)")
            conn.execute("CREATE TABLE IF NOT EXISTS edges (id INTEGER PRIMARY KEY AUTOINCREMENT, edge_type TEXT NOT NULL, from_node_id INTEGER NOT NULL, to_node_id INTEGER NOT NULL, source_table TEXT, source_pk TEXT, evidence_class TEXT, confidence_score REAL, confidence_label TEXT, rule_name TEXT, payload TEXT NOT NULL, UNIQUE(edge_type, from_node_id, to_node_id, source_table))")

    def _connect(self):
        return sqlite3.connect(self.path)

    @staticmethod
    def _node(row) -> Node:
        return Node(kg_node_id=row[0], node_type=row[1], canonical_key=row[2], display_label=row[3], source_table=row[4], source_pk=row[5], evidence_class=row[6], confidence_score=row[7], confidence_label=row[8], payload=json.loads(row[9] or "{}"))

    @staticmethod
    def _edge(row) -> Edge:
        return Edge(kg_edge_id=row[0], edge_type=row[1], from_node_id=row[2], to_node_id=row[3], source_table=row[4], source_pk=row[5], evidence_class=row[6], confidence_score=row[7], confidence_label=row[8], rule_name=row[9], payload=json.loads(row[10] or "{}"))

    def get_node(self, node_id: int) -> Node | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return self._node(row) if row else None

    def get_node_by_key(self, canonical_key: str) -> Node | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE canonical_key = ?", (canonical_key,)).fetchone()
        return self._node(row) if row else None

    def find_genus_node(self, genus_name: str) -> Node | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE node_type = 'genus' AND lower(display_label) = lower(?) LIMIT 1", (genus_name.strip(),)).fetchone()
        return self._node(row) if row else None

    def get_nodes(self, node_ids: Iterable[int]) -> list[Node]:
        ids = list(node_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM nodes WHERE id IN ({placeholders})", ids).fetchall()
        return [self._node(row) for row in rows]

    def get_outgoing_edges(self, node_ids, edge_types=None, limit=100, offset=0):
        ids = list(node_ids)
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        sql = f"SELECT * FROM edges WHERE from_node_id IN ({placeholders})"
        params = list(ids)
        if edge_types:
            types = list(edge_types)
            sql += " AND edge_type IN (" + ",".join("?" for _ in types) + ")"
            params.extend(types)
        sql += " ORDER BY id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [self._edge(row) for row in rows]

    def all_nodes(self) -> list[Node]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM nodes").fetchall()
        return [self._node(row) for row in rows]

    def all_edges(self) -> list[Edge]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM edges").fetchall()
        return [self._edge(row) for row in rows]

    def upsert_node(self, node: Node) -> Node:
        payload = json.dumps(node.payload or {}, default=str)
        values = (node.node_type, node.canonical_key, node.display_label, node.source_table, str(node.source_pk) if node.source_pk is not None else None, node.evidence_class, node.confidence_score, node.confidence_label, payload)
        with self._connect() as conn:
            conn.execute("INSERT INTO nodes(node_type, canonical_key, display_label, source_table, source_pk, evidence_class, confidence_score, confidence_label, payload) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(canonical_key) DO UPDATE SET node_type=excluded.node_type, display_label=excluded.display_label, source_table=excluded.source_table, source_pk=excluded.source_pk, evidence_class=excluded.evidence_class, confidence_score=excluded.confidence_score, confidence_label=excluded.confidence_label, payload=excluded.payload", values)
        return self.get_node_by_key(node.canonical_key)

    def upsert_edge(self, edge: Edge) -> Edge:
        payload = json.dumps(edge.payload or {}, default=str)
        values = (edge.edge_type, edge.from_node_id, edge.to_node_id, edge.source_table, str(edge.source_pk) if edge.source_pk is not None else None, edge.evidence_class, edge.confidence_score, edge.confidence_label, edge.rule_name, payload)
        with self._connect() as conn:
            conn.execute("INSERT OR IGNORE INTO edges(edge_type, from_node_id, to_node_id, source_table, source_pk, evidence_class, confidence_score, confidence_label, rule_name, payload) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
            row = conn.execute("SELECT * FROM edges WHERE edge_type = ? AND from_node_id = ? AND to_node_id = ? AND source_table IS ?", (edge.edge_type, edge.from_node_id, edge.to_node_id, edge.source_table)).fetchone()
        return self._edge(row)

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {"nodes": conn.execute("SELECT count(*) FROM nodes").fetchone()[0], "edges": conn.execute("SELECT count(*) FROM edges").fetchone()[0]}
