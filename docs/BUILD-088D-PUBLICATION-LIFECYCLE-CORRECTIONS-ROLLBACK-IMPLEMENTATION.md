# BUILD-088D — Publication Lifecycle, Corrections, and Rollback

## Scope and architecture compliance

BUILD-088D completes the BUILD-088A post-publication lifecycle without rewriting Layers 1–3, publication records, graph versions, object versions, or provenance. It reuses BUILD-088B authority/registry records and BUILD-088C transactions, versions, provenance, locking, and projections.

Scientific supersession, correction, withdrawal, retraction, restoration, reevaluation, and technical rollback remain distinct typed operations. No public endpoint or caller-controlled state assignment is introduced.

## Lifecycle and scientific lineage

The database transition guard adds `REEVALUATION_REQUIRED`, `SUPERSEDED`, `WITHDRAWN`, `RETRACTED`, `ROLLBACK_REQUIRED`, and `ROLLED_BACK` with the exact BUILD-088A paths. Every transition is append-only and atomically accompanied by authority, reason, correlation, lineage/action, projection, impact, and audit records.

Supersession requires separately published predecessor and successor records and a distinct/new assertion version. It records bidirectional-queryable lineage, preserves both graph versions and provenances, makes the predecessor historical, and keeps the successor authoritative. Correction is the same governed replacement plus a trusted BUILD-087 correction-record reference; it never edits either assertion or publication.

## Withdrawal, retraction, and restoration

Withdrawal records loss of publisher endorsement, removes the publication from the authoritative projection, and retains historical/provenance visibility without declaring evidence false. Retraction uses explicit scientific/integrity/legal reason categories, records the invalidation source, excludes current authority, exposes the retracted projection, and marks direct dependents `REEVALUATION_REQUIRED` rather than automatically retracting them.

BUILD-088A restoration is implemented only as `WITHDRAWN -> PUBLISHED` after trusted validation. The withdrawal event remains immutable. A retracted publication cannot be directly restored; it requires a new assertion/publication decision and graph transaction.

## Reevaluation and downstream impact

Reevaluation records preserve trigger type/reference and affected graph objects. Dependency propagation is deterministic, cycle-safe for the root, bounded to 1–500 records, idempotent, checkpointed, and resumable at the persistence layer. It makes no automatic scientific conclusion beyond `REEVALUATION_REQUIRED`.

The downstream-impact registry records refresh/reevaluation work for authoritative/historical/provenance projections, search, species/genus consumers, reasoning, conservation, breeding, scientific review, glossary/education/explanation consumers, caches, and materialized views. Consumer execution remains outside this build.

## Technical rollback

Rollback accepts only enumerated immediate technical integrity failures—not scientific disagreement, new evidence, taxonomy change, policy evolution, withdrawal, or retraction. The immutable manifest loads the original trusted transaction, failed and coherent graph versions, graph objects, provenance links, projection preconditions, and deterministic inverse projection operation.

Execution requires `ROLLBACK_REQUIRED`, holds the controlled graph publication lock and current-pointer row lock, verifies the failed version is still current, atomically restores the parent coherent version, creates an immutable rollback transaction/projection/impact/audit, and transitions to `ROLLED_BACK`. It never deletes the original transaction, graph version, object versions, or provenance.

## Projections, idempotency, concurrency, and audit

Append-only projection events provide authoritative-current, historical, withdrawn, retracted, and rolled-back views. Unique fingerprints suppress duplicate lifecycle events, lineage, reevaluation, rollback, and impacts. Publication advisory locks serialize withdrawal/retraction/restoration/supersession; sorted dual locks prevent successor races; the graph lock and pointer lock prevent rollback/publication races.

All scientifically meaningful records use the same transaction as their lifecycle and audit events. Immutable-table triggers reject update/delete. Failures therefore roll back lifecycle, projection, impact, lineage, and audit together.

## Database changes and security

`088d_publication_lifecycle_corrections_rollback.sql` adds lineage, lifecycle actions, projection events/views, reevaluation/dependency/checkpoint records, downstream impacts, rollback manifests/transactions, indexes, transition constraints, and immutability triggers. It contains no table drop, truncation, history deletion, or graph-version rewrite.

The internal API accepts only identifiers, typed reasons, trusted service/authority references, and correlation IDs. It does not accept assertion content, provenance, lifecycle state, graph versions, inverse operations, or audit identity.

## Performance and explicit exclusions

Current-state, lineage, dependency, impact, and projection paths are indexed. Propagation is bounded, manifests reference object IDs rather than loading graph history, and operations avoid full graph scans or N+1 provenance traversal.

No continuous reevaluation engine, downstream consumer implementation, reviewer UI, reasoning engine, educational graph, or BUILD-088E final integration validation is included.

## Validation and readiness

- Local focused BUILD-088D through BUILD-078 regression: 42 passed and 4 PostgreSQL-dependent tests skipped because `TEST_DATABASE_URL` was unavailable.
- GitHub PostgreSQL 16 BUILD-088D: 4 passed in 0.55 seconds. This exercised migration upgrades, non-destructive supersession, withdrawal/restoration/retraction, dependency reevaluation, conflicting concurrent actions, downstream impacts, technical rollback preparation/execution, coherent current-version restoration, and duplicate suppression.
- Isolated GitHub BUILD-088C/B/087/078 regression: 42 passed in 1.69 seconds. Historical migrations run in a separate database so no older migration is incorrectly applied as a downgrade over BUILD-088D states.
- Knowledge Graph API/traversal/orchestrator/telemetry, genus-media, and route regression: 62 passed locally.
- Full backend: 717 passed, 23 skipped, and one independently reproduced unrelated legacy BUILD-085 Windows subprocess failure. That test replaces the complete child environment with only `PYTHONPATH`; BUILD-088D modifies neither the test nor its validation script.
- Ruff, Python compilation, migration execution, and `git diff --check`: passed.

PostgreSQL lifecycle, concurrency, projection, propagation, rollback, immutability, and regression guarantees are validated. This Draft, unmerged implementation is ready for BUILD-088E final validation.
