"""Temporary disk-backed graph used only by resumable dry runs."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
