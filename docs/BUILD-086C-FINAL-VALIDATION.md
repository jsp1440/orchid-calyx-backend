# BUILD-086C — Final Integration Validation and Review Readiness

## Verdict

**NOT READY**

Exact blocker: BUILD-086A and BUILD-086B expose their API runtime through process-local `MemoryCandidateRepository` and `MemoryAggregateRepository` instances. Therefore database transaction isolation, rollback, advisory-lock cleanup, durable concurrent-submission idempotency, and process-restart recovery cannot be validated. In addition, cluster/aggregate list APIs lack pagination and explicit deterministic sorting; missing records can surface dictionary errors instead of contractual 404 responses; and there is no unavailable-service response contract.

Smallest corrective action: replace the API runtime's in-memory candidate/aggregate repositories with the already-defined additive PostgreSQL schemas, add pagination plus deterministic ordering and explicit 404/unavailable-service handling, then rerun BUILD-086C transaction and restart validation.

## Commits and prerequisites

- Repository: `jsp1440/orchid-calyx-backend`
- Tested `main`: `d6e2cbb37dffc733ec3fea52e22ce70716713389`
- BUILD-086A merge: `bc893e3edb16fb4d515c873b4e79f6959b9c760a` (PR #81)
- BUILD-086B merge/current tested main: `d6e2cbb37dffc733ec3fea52e22ce70716713389` (PR #82)
- BUILD-086C validation implementation: recorded in the Draft PR commit history

Both required additive migrations are present: `086a_candidate_knowledge.sql` and `086b_evidence_aggregation.sql`. `DATABASE_URL` was not configured in this environment, so no database migration was applied. No reset, drop, truncate, or protected-schema operation was performed.

## Test totals

- BUILD-086C focused: **6 passed, 0 skipped, 0 failed**
- BUILD-082 through BUILD-086C regression matrix: **84 passed, 0 skipped, 0 failed**
- Full backend: **679 passed, 17 skipped, 1 failed**
- The sole full-suite failure is the pre-existing Windows-only BUILD-085 operational-launch subprocess test, which replaces the complete child environment with only `PYTHONPATH`; it is unrelated to BUILD-086.
- Compile checks: passed
- `git diff --check`: passed
- PostgreSQL migration execution: not run (`DATABASE_URL` unavailable)

## Deterministic quality corpus

The 19-record controlled corpus covers duplicate evidence, independent corroboration, explicit contradiction, conditional/method-dependent evidence, supersession, taxonomic ambiguity, temporal disagreement, geographic disagreement, incompatible methods, source/citation dependence, incomplete provenance, and malformed records. It uses no production corpus and no network service.

Results:

- Duplicate detection precision: **1.00**
- Duplicate detection recall: **1.00**
- Contradiction detection precision: **1.00**
- Contradiction detection recall/conflict recall: **1.00**
- Independent-source identification accuracy: **1.00**
- Duplicate-inflation prevention: **passed**
- False consensus rate: **0.00**
- Taxonomic ambiguity routing: **passed**
- Measurement incompatibility handling/no pooling: **passed**
- Temporal disagreement visibility: **passed**
- Geographic scoping/no universalization: **passed**
- Original candidate IDs, versions, revisions, and anchors preserved: **passed**
- Uncertain/malformed/incomplete cases routed or rejected: **passed**

These scores validate the compact deterministic corpus only; they are not production scientific-accuracy claims.

## API contracts

Passed: repository-standard authentication dependencies, request-model validation, basic filters, malformed-input rejection, protected-schema separation, absence of publication endpoints, and absence of immutable-evidence mutation endpoints.

Not ready:

- no pagination contract for cluster and aggregate list APIs;
- no explicit deterministic sort contract;
- incomplete not-found handling;
- no unavailable-service response contract.

## Performance and concurrency

A controlled 500-candidate run completed in approximately 0.28 seconds on this Windows validation host (about 1,800 candidates/second) with approximately 5.5 MB traced peak memory and 51 clusters. Four isolated 20-candidate concurrent runs completed successfully in approximately 0.02 seconds. Large-cluster execution, cancellation/resume unit behavior, and bounded fixture memory passed.

Not validated because the runtime is process-local memory: shared concurrent submissions, transaction isolation, rollback, advisory-lock cleanup, durable restart/resume, and database-backed large-cluster behavior.

## Security

Passed static and contract validation for authorization dependencies, secret-marker scanning, unsafe structured-input rejection, protected-schema isolation, no Google Drive write calls/scopes, no Knowledge Graph/taxon/claim/aggregate publication calls, no path/file API surface, safe error reporting, and retained review audit events. No secret values are stored in the report or fixtures.

## Provenance and immutability

Validation observed zero candidate mutations, zero canonical evidence mutations, zero production graph mutations, and complete exact-anchor retention. Preview remains non-mutating and every aggregate remains unpublished.

## Remaining limitations

The corpus is deterministic and deliberately compact. Production-scale scientific accuracy, database transaction behavior, process recovery, API pagination/order/error contracts, penetration testing, and configured PostgreSQL migration execution remain unproven. Those gaps prevent BUILD-086 review readiness.
