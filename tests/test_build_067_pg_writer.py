"""BUILD-067 tests: writable PostgreSQL graph repository.

The publisher-contract test runs with no database.  All database-backed tests
run against a *throwaway isolated schema* created and dropped per module — they
NEVER touch the production ``oc_graph`` tables.  They are skipped when no
DATABASE_URL is configured.
"""

from __future__ import annotations

import os
import uuid

import pytest

from runtime.knowledge_graph import (
    Edge,
    Node,
    WritablePostgresGraphRepository,
    validate_graph,
)
from runtime.knowledge_graph.publisher import EdgeSpec, NodeSpec, _Writer, publish_domain
from runtime.knowledge_graph.orchestrator import DomainAdapter

DSN = os.environ.get("DATABASE_URL")
_needs_db = pytest.mark.skipif(not DSN, reason="no DATABASE_URL for isolated DB test")

_DDL = """
CREATE SCHEMA {s};
CREATE TABLE {s}.kg_nodes (
  kg_node_id bigserial PRIMARY KEY,
  node_type text NOT NULL, canonical_key text NOT NULL,
  display_label text, source_table text, source_pk text, source_pk_json jsonb,
  evidence_class text, confidence_score numeric, confidence_label text,
  payload_json jsonb DEFAULT '{{}}'::jsonb, is_active boolean DEFAULT true,
  build_run_id bigint, created_at timestamptz DEFAULT now(),
  updated_at timestamptz DEFAULT now(),
  CONSTRAINT kg_nodes_unique UNIQUE (node_type, canonical_key)
);
CREATE TABLE {s}.kg_edges (
  kg_edge_id bigserial PRIMARY KEY,
  edge_type text NOT NULL,
  from_node_id bigint NOT NULL REFERENCES {s}.kg_nodes(kg_node_id),
  to_node_id bigint NOT NULL REFERENCES {s}.kg_nodes(kg_node_id),
  source_table text, source_pk text, source_pk_json jsonb,
  evidence_class text NOT NULL, confidence_score numeric, confidence_label text,
  rule_name text, payload_json jsonb DEFAULT '{{}}'::jsonb,
  is_active boolean DEFAULT true, build_run_id bigint,
  created_at timestamptz DEFAULT now(), updated_at timestamptz DEFAULT now()
);
"""


# --- publisher contract (no database) ---------------------------------------

def test_publisher_accepts_writable_repo_without_typeerror():
    """The exact BUILD-066 blocker: publisher must accept the prod repo."""
    repo = WritablePostgresGraphRepository("postgres://unused", schema="oc_graph")
    # Constructing _Writer must not raise TypeError (hasattr upsert_*).
    writer = _Writer(repo)
    assert writer is not None
    assert hasattr(repo, "upsert_node") and hasattr(repo, "upsert_edge")
    assert hasattr(repo, "get_node_by_key")


# --- database-backed tests (isolated schema) --------------------------------

@pytest.fixture()
def schema():
    import psycopg
    name = "kg_w_test_" + uuid.uuid4().hex[:12]
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(_DDL.format(s=name))
    try:
        yield name
    finally:
        with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f"DROP SCHEMA {name} CASCADE")


def _seed_taxon(schema: str, pk: str = "10", label: str = "Cattleya labiata") -> int:
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    n = repo.upsert_node(Node(
        kg_node_id=0, node_type="taxon", canonical_key=f"taxon:{pk}",
        display_label=label, source_table="oc_graph.kg_nodes", source_pk=pk,
        evidence_class="curated", confidence_score=1.0, confidence_label="high",
        payload={"rank": "species"},
    ))
    repo.commit()
    repo.close()
    return n.kg_node_id


def _count(schema: str, table: str) -> int:
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {schema}.{table} WHERE is_active")
        return cur.fetchone()[0]


@_needs_db
def test_node_upsert_insert_and_idempotent(schema):
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    spec = Node(kg_node_id=0, node_type="trait", canonical_key="trait:t1",
                display_label="flower_color", source_table="oc.traits", source_pk="t1",
                evidence_class="observed", confidence_score=0.9, confidence_label="med",
                payload={"k": "v"})
    a = repo.upsert_node(spec)
    b = repo.upsert_node(spec)  # idempotent
    repo.commit(); repo.close()
    assert a.kg_node_id == b.kg_node_id
    assert _count(schema, "kg_nodes") == 1


@_needs_db
def test_get_node_by_key_uncommitted_and_committed(schema):
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:t9",
                          display_label="x", source_table="oc.traits", source_pk="t9",
                          evidence_class="observed"))
    # visible within the open transaction before commit
    assert repo.get_node_by_key("trait:t9") is not None
    repo.commit(); repo.close()
    repo2 = WritablePostgresGraphRepository(DSN, schema=schema)
    assert repo2.get_node_by_key("trait:t9") is not None
    repo2.close()


@_needs_db
def test_edge_upsert_insert_and_idempotent(schema):
    taxon_id = _seed_taxon(schema)
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    trait = repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:t1",
                                  display_label="c", source_table="oc.traits", source_pk="t1",
                                  evidence_class="observed"))
    e = Edge(kg_edge_id=0, edge_type="has_trait", from_node_id=taxon_id,
             to_node_id=trait.kg_node_id, source_table="oc.traits", source_pk="t1",
             evidence_class="observed", rule_name="r1", payload={"p": 1})
    e1 = repo.upsert_edge(e)
    e2 = repo.upsert_edge(e)  # dedup, no new row
    repo.commit(); repo.close()
    assert e1.kg_edge_id == e2.kg_edge_id
    assert _count(schema, "kg_edges") == 1


@_needs_db
def test_len_all_edges_tracks_writes_without_full_scan(schema):
    taxon_id = _seed_taxon(schema)
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    trait = repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:t1",
                                  display_label="c", source_table="oc.traits", source_pk="t1",
                                  evidence_class="observed"))
    before = len(repo.all_edges())
    repo.upsert_edge(Edge(kg_edge_id=0, edge_type="has_trait", from_node_id=taxon_id,
                          to_node_id=trait.kg_node_id, source_table="oc.traits",
                          source_pk="t1", evidence_class="observed"))
    after_insert = len(repo.all_edges())
    repo.upsert_edge(Edge(kg_edge_id=0, edge_type="has_trait", from_node_id=taxon_id,
                          to_node_id=trait.kg_node_id, source_table="oc.traits",
                          source_pk="t1", evidence_class="observed"))
    after_dup = len(repo.all_edges())
    repo.rollback(); repo.close()
    assert after_insert == before + 1
    assert after_dup == after_insert  # dedup does not grow the count


@_needs_db
def test_rollback_leaves_graph_unchanged(schema):
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:rb",
                          display_label="x", source_table="oc.traits", source_pk="rb",
                          evidence_class="observed"))
    repo.rollback(); repo.close()
    assert _count(schema, "kg_nodes") == 0


@_needs_db
def test_transaction_failure_leaves_no_partial_batch(schema):
    """A bad edge (missing FK endpoint) inside a run must abort the whole run."""
    taxon_id = _seed_taxon(schema)
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    good = repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:g",
                                 display_label="g", source_table="oc.traits", source_pk="g",
                                 evidence_class="observed"))
    with pytest.raises(Exception):
        # to_node_id 999999 violates the FK -> error inside the transaction
        repo.upsert_edge(Edge(kg_edge_id=0, edge_type="has_trait", from_node_id=taxon_id,
                              to_node_id=999999, source_table="oc.traits", source_pk="g",
                              evidence_class="observed"))
    repo.rollback(); repo.close()
    # the good node written in the same aborted run must not persist
    assert _count(schema, "kg_nodes") == 1  # only the pre-seeded taxon
    assert good.kg_node_id  # id was assigned but rolled back


@_needs_db
def test_node_and_edge_updates_preserve_provenance(schema):
    taxon_id = _seed_taxon(schema)
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:p",
                          display_label="v1", source_table="oc.traits", source_pk="p",
                          evidence_class="observed"))
    repo.commit()
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"SELECT created_at FROM {schema}.kg_nodes WHERE canonical_key='trait:p'")
        created1 = cur.fetchone()[0]
    # re-publish (idempotent update)
    repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:p",
                          display_label="v2", source_table="oc.traits", source_pk="p",
                          evidence_class="observed"))
    repo.commit(); repo.close()
    with psycopg.connect(DSN, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"SELECT created_at, display_label, source_table, source_pk "
                    f"FROM {schema}.kg_nodes WHERE canonical_key='trait:p'")
        created2, label, stab, spk = cur.fetchone()
    assert created2 == created1          # provenance timestamp preserved
    assert label == "v2"                 # content refreshed
    assert stab == "oc.traits" and spk == "p"  # source provenance intact


def _trait_adapter() -> DomainAdapter:
    def produce(rows):
        nodes, edges = [], []
        for r in rows:
            nodes.append(NodeSpec(node_type="trait", source_pk=r["source_pk"],
                                  display_label=r["trait_name"], source_table="oc.traits",
                                  evidence_class="observed"))
            edges.append(EdgeSpec(edge_type="has_trait",
                                  from_key=f"taxon:{r['taxon_pk']}",
                                  to_key=f"trait:{r['source_pk']}",
                                  source_table="oc.traits", source_pk=r["source_pk"],
                                  evidence_class="observed"))
        return nodes, edges
    return DomainAdapter(domain="traits", source_table="oc.traits", produce=produce)


@_needs_db
def test_publisher_end_to_end_and_idempotent_republish(schema):
    _seed_taxon(schema)
    adapter = _trait_adapter()
    rows = [{"source_pk": "t1", "taxon_pk": "10", "trait_name": "flower_color"},
            {"source_pk": "t2", "taxon_pk": "10", "trait_name": "leaf_shape"}]
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    r1 = publish_domain(repo, adapter, rows)
    v = validate_graph(repo)
    repo.commit(); repo.close()
    assert r1.nodes_written == 2 and r1.edges_written == 2
    assert v["healthy"], v
    assert _count(schema, "kg_nodes") == 3  # taxon + 2 traits
    assert _count(schema, "kg_edges") == 2

    # re-publish: identical contents, nothing new
    repo2 = WritablePostgresGraphRepository(DSN, schema=schema)
    r2 = publish_domain(repo2, adapter, rows)
    repo2.commit(); repo2.close()
    assert r2.nodes_written == 0 and r2.edges_written == 0
    assert r2.skipped_existing_nodes == 2 and r2.skipped_existing_edges == 2
    assert _count(schema, "kg_nodes") == 3 and _count(schema, "kg_edges") == 2


@_needs_db
def test_resume_after_interrupted_publish(schema):
    """First run commits domain, second (resume) republishes idempotently."""
    _seed_taxon(schema)
    adapter = _trait_adapter()
    rows = [{"source_pk": "t1", "taxon_pk": "10", "trait_name": "flower_color"}]
    # interrupted run: write but simulate crash before commit -> rollback
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    publish_domain(repo, adapter, rows)
    repo.rollback(); repo.close()
    assert _count(schema, "kg_nodes") == 1  # only taxon; trait rolled back

    # resume: re-run the same domain, now commit -> converges
    repo2 = WritablePostgresGraphRepository(DSN, schema=schema)
    r = publish_domain(repo2, adapter, rows)
    repo2.commit(); repo2.close()
    assert r.nodes_written == 1 and r.edges_written == 1
    assert _count(schema, "kg_nodes") == 2 and _count(schema, "kg_edges") == 1


# --- BUILD-068 regression tests (production-fidelity writer bugs) ------------

@_needs_db
def test_edge_null_evidence_class_defaults_to_normalized(schema):
    """Prod kg_edges.evidence_class is NOT NULL. Adapters that omit it produce
    Edge.evidence_class=None; the writer must substitute 'normalized' (the
    graph-wide convention) rather than raising a NOT NULL violation."""
    taxon_id = _seed_taxon(schema)
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    trait = repo.upsert_node(Node(kg_node_id=0, node_type="trait", canonical_key="trait:ev",
                                  display_label="c", source_table="oc.traits", source_pk="ev",
                                  evidence_class="observed"))
    e = repo.upsert_edge(Edge(kg_edge_id=0, edge_type="has_trait", from_node_id=taxon_id,
                              to_node_id=trait.kg_node_id, source_table="oc.traits",
                              source_pk="ev", evidence_class=None))  # adapter omitted it
    repo.commit(); repo.close()
    assert e.evidence_class == "normalized"
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"SELECT evidence_class FROM {schema}.kg_edges WHERE kg_edge_id=%s",
                    (e.kg_edge_id,))
        assert cur.fetchone()[0] == "normalized"


@_needs_db
def test_node_edge_decimal_and_datetime_payload_serializable(schema):
    """Payloads sourced from Postgres carry Decimal/date values. The writer must
    JSON-serialize them into jsonb (Decimal->number, temporal->ISO) rather than
    raising 'Object of type Decimal is not JSON serializable'."""
    from datetime import date
    from decimal import Decimal
    taxon_id = _seed_taxon(schema)
    repo = WritablePostgresGraphRepository(DSN, schema=schema)
    node = repo.upsert_node(Node(
        kg_node_id=0, node_type="literature", canonical_key="lit:d1",
        display_label="ref", source_table="oc.lit", source_pk="d1",
        evidence_class="observed",
        payload={"year": Decimal("2021"), "score": Decimal("3.14"), "pub": date(2021, 5, 1)}))
    repo.upsert_edge(Edge(kg_edge_id=0, edge_type="cited_in", from_node_id=taxon_id,
                          to_node_id=node.kg_node_id, source_table="oc.lit", source_pk="d1",
                          evidence_class="observed", payload={"n": Decimal("7")}))
    repo.commit(); repo.close()
    import psycopg
    with psycopg.connect(DSN, autocommit=True) as c, c.cursor() as cur:
        cur.execute(f"SELECT payload_json FROM {schema}.kg_nodes WHERE canonical_key='lit:d1'")
        p = cur.fetchone()[0]
    assert p["year"] == 2021 and abs(p["score"] - 3.14) < 1e-9 and p["pub"] == "2021-05-01"


@_needs_db
def test_large_batch_dedup_and_idempotent_rerun(schema):
    """Exercises the in-memory taxonomy/edge caches on a many-row publish:
    first run inserts all, a second identical run inflates nothing and resolves
    every edge to its existing id."""
    _seed_taxon(schema)
    adapter = _trait_adapter()
    rows = [{"source_pk": f"t{i}", "taxon_pk": "10", "trait_name": f"trait_{i}"}
            for i in range(150)]
    repo = WritablePostgresGraphRepository(DSN, schema=schema, commit_every=50)
    r1 = publish_domain(repo, adapter, rows)
    repo.commit(); repo.close()
    assert r1.nodes_written == 150 and r1.edges_written == 150
    assert _count(schema, "kg_nodes") == 151 and _count(schema, "kg_edges") == 150

    repo2 = WritablePostgresGraphRepository(DSN, schema=schema)
    r2 = publish_domain(repo2, adapter, rows)
    repo2.commit(); repo2.close()
    assert r2.nodes_written == 0 and r2.edges_written == 0
    assert r2.skipped_existing_nodes == 150 and r2.skipped_existing_edges == 150
    assert _count(schema, "kg_nodes") == 151 and _count(schema, "kg_edges") == 150
