# BUILD-067 — Production Knowledge Graph Writer

Branch: `feat/scientific-knowledge-graph-completion` · PR #56 · Not merged.

## Objective
Implement the missing production write capability for the knowledge graph: a
writable PostgreSQL repository satisfying the same contract as
`InMemoryGraphRepository` (`upsert_node`, `upsert_edge`, `get_node_by_key`), so
the **unchanged** publisher/orchestrator can write to production. This was the
sole blocker identified by BUILD-066 (`PostgresGraphRepository` was read-only,
so the publisher raised `TypeError("publisher requires a writable repository")`).

## What was added (no existing component modified)
- `WritablePostgresGraphRepository` (extends `PostgresGraphRepository`) in
  `runtime/knowledge_graph/repository.py`.
- Package export in `runtime/knowledge_graph/__init__.py`.
- Additive, un-executed helper `runtime/knowledge_graph/production_publish.py`
  wiring the unchanged orchestrator to the writer with run-level commit/rollback.
- `tests/test_build_067_pg_writer.py` (10 tests).

Publisher, orchestrator, checkpoint system, validation, canonical taxonomy,
source registry, and batch processing are byte-for-byte unchanged.

## Design decisions
- **Node persistence** — `INSERT ... ON CONFLICT (node_type, canonical_key) DO
  UPDATE`, matching the existing `kg_nodes_unique` index. `created_at` is never
  touched on update, preserving provenance timestamps. Identity unchanged.
- **Edge persistence** — `kg_edges` has no unique constraint and none was added
  (schema frozen). Idempotency uses `INSERT ... WHERE NOT EXISTS` on the
  existing logical identity `(edge_type, from_node_id, to_node_id, source_table)`
  with `IS NOT DISTINCT FROM` for NULL-safe matching — mirrors the in-memory
  dedup key exactly.
- **Transactions** — single persistent connection, autocommit disabled. Default
  is a **run-level transaction**: the whole build commits once on success or
  rolls back as a unit; no partial batches are ever committed. `commit_every`
  optionally enables incremental commits for very large runs (idempotency makes
  a subsequent RESUME converge to identical contents).
- **Read performance** — the frozen publisher measures `len(all_edges())` before
  and after every `upsert_edge`. To avoid an O(n) table scan per edge, the
  writer returns a `_LazyEdgeView` whose `len()` is an O(1) live counter;
  iteration (used only by validation/quality/reporting, once per domain) lazily
  loads real rows. No validation behavior was weakened.
- **Uncommitted visibility** — read methods reuse the open write transaction so
  `validate_graph` sees pending writes before commit; when idle, they fall back
  to the parent's short-lived read connection (API read paths unaffected).

## Test evidence
`tests/test_build_067_pg_writer.py` — **10 passed in 14.27s**. DB-backed tests
run against a throwaway isolated schema (`kg_w_test_<uuid>`), created and dropped
per run; they NEVER touch `oc_graph`. The publisher-contract test runs with no
database. Coverage:
- publisher accepts the writable prod repo (no `TypeError`);
- node upsert insert + idempotent;
- edge upsert insert + idempotent;
- `get_node_by_key` (uncommitted + committed);
- `len(all_edges())` tracks writes without full scan;
- rollback leaves the graph unchanged;
- transaction failure leaves no partial batch;
- node/edge updates preserve provenance (`created_at`, source_table/pk);
- publisher end-to-end + idempotent re-publish (0 new on second run);
- interrupted publication resumes correctly.

Existing `tests/test_build_066_graph_completion.py` — **10 passed**, unchanged.

## BUILD-066 full DRY_RUN (validation only — no production writes)
Run through the unchanged orchestrator/publisher:
- **Publisher accepts the production repository — no `TypeError`.**
- Mode `dry_run`, `wrote_to_production=False`, duration ~41.6s.
- Projected totals: **22,492 nodes / 22,827 edges** (identical to prior BUILD-066).
- Per-domain: all 8 domains `completed`.
- `cross_domain healthy=False`, `orphan_nodes=14481` — this is the pre-existing
  climate-proxy dry-run characteristic (staging seeds only taxonomy, so climate
  proxy nodes appear orphaned in dry-run); unchanged from BUILD-066, not
  introduced here. It does not affect the real-publish path, where taxonomy
  already exists in production.

## Production safety
- No production writes performed. `oc_graph` before = after: **34,519 active
  nodes / 67,572 active edges** (unchanged). No leftover test schemas.
- BUILD-067 ends at validation. A production publish requires separate explicit
  owner authorization (BUILD-066 rerun with the new repository will follow).

## Verdict
**PRODUCTION GRAPH WRITER COMPLETE**
