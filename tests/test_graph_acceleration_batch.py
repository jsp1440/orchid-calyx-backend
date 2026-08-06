import os
import sqlite3
import time

import pytest

from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.resumable_dry_run import DryRunSession
from runtime.knowledge_graph.resumable_executor import (
    LOCK_STALE_SECONDS,
    lock_path,
    session_report,
    session_resume_lock,
    staging_path,
)
from runtime.knowledge_graph.sqlite_staging import SqliteStagingGraphRepository


def test_null_source_edge_is_idempotent(tmp_path):
    repo = SqliteStagingGraphRepository(str(tmp_path / "staging.sqlite3"))
    taxon = repo.upsert_node(Node(0, "taxon", "taxon:1", "Test orchid", "taxonomy", "1", None, None, None, {}))
    image = repo.upsert_node(Node(0, "image", "image:1", "Image", None, "1", None, None, None, {}))
    edge = Edge(0, "has_image", taxon.kg_node_id, image.kg_node_id, None, "1", None, None, None, None, {})
    repo.upsert_edge(edge)
    repo.upsert_edge(edge)
    assert repo.counts()["edges"] == 1


def test_legacy_duplicate_null_edges_are_migrated_safely(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE nodes (id INTEGER PRIMARY KEY AUTOINCREMENT, node_type TEXT NOT NULL, canonical_key TEXT NOT NULL UNIQUE, display_label TEXT, source_table TEXT, source_pk TEXT, evidence_class TEXT, confidence_score REAL, confidence_label TEXT, payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE edges (id INTEGER PRIMARY KEY AUTOINCREMENT, edge_type TEXT NOT NULL, from_node_id INTEGER NOT NULL, to_node_id INTEGER NOT NULL, source_table TEXT, source_pk TEXT, evidence_class TEXT, confidence_score REAL, confidence_label TEXT, rule_name TEXT, payload TEXT NOT NULL, UNIQUE(edge_type, from_node_id, to_node_id, source_table))")
        values = ("has_image", 1, 2, None, "1", None, None, None, None, "{}")
        conn.execute("INSERT INTO edges(edge_type, from_node_id, to_node_id, source_table, source_pk, evidence_class, confidence_score, confidence_label, rule_name, payload) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
        conn.execute("INSERT INTO edges(edge_type, from_node_id, to_node_id, source_table, source_pk, evidence_class, confidence_score, confidence_label, rule_name, payload) VALUES(?,?,?,?,?,?,?,?,?,?)", values)
    repo = SqliteStagingGraphRepository(str(path))
    assert repo.counts()["edges"] == 1
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT source_table FROM edges").fetchone()[0] == ""


def test_pending_status_does_not_create_sqlite_file(tmp_path):
    session = DryRunSession.create(["media"], batch_size=10, max_batches_per_step=1)
    path = staging_path(str(tmp_path), session.run_id)
    report = session_report(session, str(tmp_path))
    assert report["staging_started"] is False
    assert report["progress"]["next_action"] == "resume"
    assert not os.path.exists(path)


def test_resume_lock_rejects_concurrent_call(tmp_path):
    with session_resume_lock(str(tmp_path), "run-1"), pytest.raises(
        RuntimeError, match="resume_already_in_progress"
    ), session_resume_lock(str(tmp_path), "run-1"):
        pass


def test_stale_resume_lock_is_recovered(tmp_path):
    target = lock_path(str(tmp_path), "run-2")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("stale", encoding="utf-8")
    old = time.time() - LOCK_STALE_SECONDS - 5
    os.utime(target, (old, old))
    with session_resume_lock(str(tmp_path), "run-2"):
        assert target.exists()
    assert not target.exists()
