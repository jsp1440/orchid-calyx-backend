# BUILD-068 — Runbook, Design & Rationale

## Preflight (checked before any write)
1. DB target resolved from `DATABASE_URL`.
2. Target tables `oc_graph.kg_nodes` / `oc_graph.kg_edges` present.
3. Writable repository (`WritablePostgresGraphRepository`) active.
4. Canonical authority == `world_plants` (Hassler); ABORT-NO-WRITES otherwise.
5. Authorized domains fixed & ordered: media, traits, pollinators, occurrences,
   literature, conservation.
6. Withheld domains (climate, mycorrhiza) confirmed absent from the authorized
   set; they are never supplied to the publisher, so they can never be written.
7. Baseline node/edge counts captured (pristine: 34,519 / 67,572).
8. Build run id minted and persisted (stable across resume).
9. Durable checkpoint path recorded.
10-14. Source read-only, per-domain source row counts captured, authorization
   flags recorded.

## Transaction, checkpoint & resume model
A single all-or-nothing transaction across all domains is **not achievable** in
this environment: the population is ~5,900 row-by-row inserts over a
high-latency write path, which exceeds one interactive execution window, and
detached background processes are reaped. Per the mandate's allowance for
unavoidable production-size limits, the driver therefore commits at
**domain granularity with intra-domain `commit_every` batches**:

- Each domain is processed to completion, then committed; a durable checkpoint
  records the domain as `completed`.
- Within a large domain (`traits`, ~2,807 rows), `commit_every=500` flushes
  partial progress so a killed call never loses committed batches and never
  restarts the whole domain endlessly.
- On any domain error the current uncommitted batch is rolled back and the run
  stops (`PARTIALLY COMPLETED — RESUME REQUIRED`).
- **Resume**: re-invoking `publish` skips already-`completed` domains and
  re-runs any incomplete one. Idempotency (below) guarantees re-processing
  committed rows inflates nothing.

Publish completed across 2 resumable windows; full validation, connectivity and
idempotency then ran as separate phases against the committed graph.

## Idempotency (zero inflation)
- Nodes: `upsert_node` no-ops when the canonical_key already exists with
  identical content; otherwise `ON CONFLICT DO UPDATE` refreshes content while
  preserving `created_at`.
- Edges: deduplicated by logical identity
  `(edge_type, from_node_id, to_node_id, source_table)`; an existing identity is
  a no-op that returns the existing edge id.
- Verified: a full 6-domain rerun produced node delta 0 / edge delta 0.

## Performance caches (writer, additive)
To make row-by-row publishing and idempotent reruns feasible without a schema
change (prod tables are frozen — no unique index on `kg_edges`), the writable
repository maintains in-memory, transaction-scoped caches:
- **Complete node-key cache**: all active nodes preloaded once; a miss
  authoritatively means "does not exist", eliminating a DB round-trip per taxon
  resolution and per new-node existence check.
- **Edge-identity map**: active edge identities → id, replacing a per-edge
  `WHERE NOT EXISTS` sequential scan.
Both are cleared on `rollback`; write-through keeps them consistent as new rows
are created. Correctness is guaranteed by single-writer execution and confirmed
by post-publish `duplicate_relationships = 0`.

## Production-fidelity writer fixes (found & fixed during BUILD-068)
1. **NULL `evidence_class` on edges** — `oc_graph.kg_edges.evidence_class` is
   `NOT NULL`, but several domain adapters omit it (→ `None`). The writer now
   substitutes `'normalized'` (the graph-wide convention). Regression test:
   `test_edge_null_evidence_class_defaults_to_normalized`.
2. **`Decimal` / temporal payloads not JSON-serializable** — payloads sourced
   from Postgres numeric/date columns broke `json.dumps` (surfaced on the
   `literature` domain). The writer now serializes `Decimal` → JSON number and
   `date`/`datetime` → ISO string into `payload_json`. Regression test:
   `test_node_edge_decimal_and_datetime_payload_serializable`.

The isolated-schema test DDL already mirrors prod's `kg_edges.evidence_class
NOT NULL`, so these regressions are caught against production-faithful schema.

## Re-run / resume commands
```
# publish (resumable; skips completed domains). Optional budget seconds arg.
PYTHONPATH=<repo> python3 b068.py publish 95
# post-publish phases:
PYTHONPATH=<repo> python3 b068.py validate
PYTHONPATH=<repo> python3 b068.py connectivity
PYTHONPATH=<repo> python3 b068.py idempotency
```

## Guardrails honored
- Withheld domains climate & mycorrhiza never written (verified 0 present).
- PR #56 NOT merged.
- Calyx API workflow NOT started.
