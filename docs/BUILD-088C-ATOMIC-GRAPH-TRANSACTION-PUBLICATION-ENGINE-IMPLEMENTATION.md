# BUILD-088C — Atomic Graph Transaction and Publication Engine

## Scope and architecture compliance

BUILD-088C implements the BUILD-088A transaction boundary after BUILD-088B authorization. It consumes only exact `AUTHORIZED` publication versions and stops before scientific supersession, withdrawal, retraction, restoration, and post-publication rollback execution.

The internal request contains only publication ID/version, controlled service identity, and correlation ID. Assertion content, eligibility, authorization, policy, provenance, graph baseline, lifecycle state, and success are loaded or produced inside trusted PostgreSQL transactions.

## Components and database changes

- Immutable graph change sets and transaction manifests bind exact publication, authorization, assertion, policy, provenance, operations, and source graph version fingerprints.
- The deterministic assertion mapper creates subject, object, and qualified-assertion nodes plus typed edges. Material units, qualifiers, taxonomy, geography, time, population, life stage, conditions, methods, uncertainty, negation, comparison, support, and conflicts remain attached to the qualified assertion instead of being flattened.
- Additive migration `088c_atomic_graph_transaction_publication_engine.sql` adds manifests, attempts, graph versions, object versions, provenance links, a constant-time current-version pointer, indexes, immutability triggers, and BUILD-088C lifecycle states.
- `PostgresControlledGraphRepository` prepares and commits through the existing `oc_graph.kg_nodes` and `kg_edges` tables. It does not introduce a parallel graph store.

## Operations and identifiers

Supported operations are `CREATE_NODE`, `CREATE_EDGE`, `ADD_ASSERTION_SUPPORT`, `ADD_CONFLICTING_EVIDENCE`, `UPDATE_PUBLICATION_STATUS`, and `NO_OP_DUPLICATE`. Destructive overwrites and BUILD-088D operations are absent. SHA-256 identities include taxonomy version, assertion version, scope, contextual qualifiers, negation, and units.

## Validation, provenance, and atomic publication

Preparation re-resolves exact publication state, authorization decision, policy, assertion/eligibility linkage, provenance, taxonomy, supported operations, and current graph version. `AUTHORIZED -> TRANSACTION_PREPARED` commits with the manifest and audit.

Publication serializes on a PostgreSQL advisory lock and current-version row. `PUBLISHING`, graph version, graph objects, object-version links, complete reverse provenance, transaction receipt, current projection pointer, audit, and `PUBLISHED` commit in one database transaction. Any write, provenance, audit, lifecycle, projection, or commit error rolls the graph transaction back; a separate immutable `PUBLICATION_FAILED` checkpoint is recorded only after rollback. Retry of a committed fingerprint returns `NO_OP_DUPLICATE`.

Graph provenance links each object version to graph transaction, publication, authorization decision, assertion, and copyright-safe source revision metadata. The trusted BUILD-088B snapshot retains interpretation and Evidence Packet linkage without copying source text.

## Versioning, projections, concurrency, retry

Graph versions are immutable parent-linked records. A singleton row exposes the current authoritative version without scanning history; object versions and provenance links provide historical and provenance projections. No provisional record can enter unless BUILD-088B has actually authorized it. Transaction and object fingerprints, unique constraints, a global publication lock, and the locked current-version pointer prevent duplicate commits and conflicting version reservations. Preparation and committed results are idempotent across retry or worker restart.

## Existing graph-writer inventory

| Path | Purpose/state | Scientific writes and governance disposition |
|---|---|---|
| `app/publication` / `PostgresPublicationRepository` | Active authenticated BUILD-078 candidate publisher | Writes semantic candidates with older provenance. Unchanged to avoid route regression; must later be governed or explicitly classified as non-Layer-3 input. |
| `runtime/knowledge_graph/publisher.py` | Active build-time domain mapper | Writes nodes/edges through repository contract. Unchanged; scientific production use remains a future governance migration. |
| `runtime/knowledge_graph/orchestrator.py` | Active PUBLISH/RESUME orchestration | Can authorize runtime publishing. Unchanged because BUILD-088A warns against broad replacement during C. |
| `runtime/knowledge_graph/production_publish.py` | Production composition | Constructs the writable repository. Unchanged; no new BUILD-088C surface exposes it. |
| `WritablePostgresGraphRepository` | Active legacy single-writer repository | Uses update-style node upsert and embedded provenance. Unchanged for regression safety. The BUILD-088C engine does not call it and never overwrites a governed node. |
| SQL migrations and validation scripts | Migration/test-only | Schema/fixture writes only; not runtime scientific publication. |

The approved BUILD-088A architecture schedules complete role/grant governance of all production-capable legacy paths. BUILD-088C adds no bypass and exposes no public write endpoint.

## Failure handling, security, and observability

Stable fail-closed reason codes cover missing/mismatched publication, decision, policy, assertion, eligibility, provenance, taxonomy, predicates, units, context, source-version conflict, and transaction failures. Transaction attempts, lifecycle events, and audits provide safe counts and latency timestamps without source text, credentials, or reviewer details. No caller can assign authorization, graph version, state, audit identity, or graph payload.

## Performance

All identity/current/history lookups are indexed. Provenance is carried as bounded references rather than full Evidence Packets. Preparation orders a bounded operation manifest; publication performs set-sized writes without graph scans. Advisory and row locks are transaction-scoped. No distributed infrastructure was introduced.

## Explicit exclusions and limitations

BUILD-088D scientific supersession, withdrawal, retraction, restoration, and technical inverse execution are not implemented. Legacy writer enforcement through database roles remains a later repository-wide migration exactly as identified by BUILD-088A. There is no public endpoint, reviewer UI, reasoning engine, or educational graph.

## Validation and readiness

- Local BUILD-088C plus BUILD-088B/087/graph regression: 39 passed and 3 PostgreSQL-dependent tests skipped because `TEST_DATABASE_URL` was unavailable.
- GitHub PostgreSQL 16 BUILD-088C: 7 passed in 0.33 seconds. This exercised migration, transaction preparation, concurrent identical publication, one-winner graph-version serialization, committed retry no-op, graph-object persistence, lifecycle completion, and reverse provenance.
- GitHub BUILD-088B, BUILD-087, and BUILD-078 graph regression: 35 passed in 1.48 seconds.
- Dedicated Knowledge Graph API/traversal/orchestrator/telemetry, genus-media, and route regression: 62 passed locally.
- Full backend: 714 passed, 22 skipped, and one unrelated legacy BUILD-085 Windows subprocess test failed. The failure is independently reproducible on unchanged main: that test replaces the child environment with only `PYTHONPATH`, which prevents its validation subprocess from initializing in this Windows runtime. BUILD-088C does not modify the test or script.
- Ruff, Python compilation, and `git diff --check`: passed.

PostgreSQL atomic, concurrency, graph-version, provenance, idempotency, and rollback-on-error invariants are validated. The implementation is ready for BUILD-088D review while this pull request remains Draft and unmerged.
