# BUILD-086D — Corrective Validation Report

## Verdict

**READY — BUILD-086 REVIEW READY**

## Commits and files

- Starting `main`: `d6e2cbb37dffc733ec3fea52e22ce70716713389`
- Corrective implementation: `aeaea5d749bc1a1cfdf77fcd4185d96d359a5512`
- CI assertion isolation: `b00a952399d832904664e215ea4d6cfeaeafa585`

Changed scope: candidate and aggregation routes; PostgreSQL repository adapters; shared state codec/transaction repository; additive migration `086d_persistent_runtime.sql`; corrected BUILD-086C validation; BUILD-086D tests; PostgreSQL CI workflow; this report. No unrelated files are included.

## Persistent repositories and migration

When `DATABASE_URL` or `TEST_DATABASE_URL` is configured, production BUILD-086A/B routes now use `PostgresCandidateRepository` and `PostgresAggregateRepository`. Without a database, the existing memory repositories remain available for deterministic unit tests.

The additive migration creates an isolated JSONB runtime snapshot table plus append-only audit history in `oc_candidate_knowledge`. It contains no reset, drop, truncate, rewrite, protected-schema reference, or publication operation. Existing BUILD-086A/B migrations remain present and unchanged.

Atomic repository operations acquire PostgreSQL transaction-scoped advisory locks, reload the latest durable state, execute one service boundary, persist a new revision, and commit. Exceptions roll back the snapshot and PostgreSQL releases locks after commit, rollback, connection loss, cancellation, or process exit. Durable state covers candidate/aggregate versions, exact anchors, plans, runs, checkpoints, cluster membership, relationships, conflicts, warnings, reviews, audit events, and tombstones.

## Restart, transactions, concurrency, and locks

Disposable PostgreSQL validation passed for:

- candidate persistence across repository/process reconstruction;
- cancellation checkpoint persistence and restart-safe resume;
- aggregate persistence across reconstruction;
- rollback with no partial saved version;
- four concurrent duplicate submissions;
- one active canonical aggregate version for the submitted identity;
- transaction isolation through advisory serialization;
- lock availability after success and controlled exceptions.

Large fixture processing remains bounded: 500 candidates completed at roughly 2,000+ candidates/second with under 100 MB traced peak memory in both local and CI validation.

## API contracts

BUILD-086A/B collection endpoints now provide bounded, validated limit/offset pagination, stable ID/version ordering, domain filters, total counts, consistent empty pages, explicit structured 404 responses, and structured 503 unavailable-service responses. Pydantic/FastAPI rejects invalid pagination and malformed JSON. Authentication remains mandatory. No public or internal publication endpoint was added.

## Security, provenance, and immutability

Parameterized PostgreSQL statements prevent value injection. Validation found no secret markers, path/file surface, Google Drive write call or scope, protected-schema write, or Knowledge Graph/taxon/claim/candidate/aggregate publication call. API keys retain the existing authentication boundary and cannot override copyright policy.

Original evidence is never written. Candidate and aggregate snapshots are append-only revisions; superseding versions remain retained. Exact candidate, revision, and anchor provenance round-trips through PostgreSQL. Audit triggers record every snapshot revision.

## Test results

Local Windows validation:

- BUILD-086C + BUILD-086D focused: **10 passed, 2 PostgreSQL-only skipped, 0 failed**
- BUILD-082 through BUILD-086D regression: **88 passed, 2 PostgreSQL-only skipped, 0 failed**
- Full backend: **683 passed, 19 skipped, 1 failed**
- The sole full-suite failure is the pre-existing Windows-only BUILD-085 subprocess-environment test; it replaces the child environment with only `PYTHONPATH` and is unrelated to BUILD-086.
- Compile checks and `git diff --check`: passed

Disposable PostgreSQL 16 CI validation:

- BUILD-086D focused PostgreSQL/API: **8 passed, 0 skipped, 0 failed**
- Corrected BUILD-086C rerun: **4 passed, 0 skipped, 0 failed**
- BUILD-082 through BUILD-086D matrix: **90 passed, 0 skipped, 0 failed**
- Candidate-knowledge validation: passed
- Evidence-aggregation validation: passed
- Compile and `git diff --check`: passed

## BUILD-086C quality rerun

The deterministic 19-record corpus retained:

- duplicate precision/recall: **1.00 / 1.00**;
- contradiction precision/recall: **1.00 / 1.00**;
- independent-source accuracy: **1.00**;
- duplicate inflation prevented: **passed**;
- false-consensus rate: **0.00**;
- taxonomy ambiguity, temporal/geographic disagreement, and measurement incompatibility handling: **passed**;
- exact anchor preservation: **passed**.

The final-validation script reported `READY — BUILD-086 REVIEW READY` with PostgreSQL persistence, restart, and lock checks passing.

## Remaining limitations

The deterministic corpus validates mechanics, not production scientific accuracy. Runtime persistence uses atomic versioned JSONB snapshots rather than row-per-domain-object writes; this is deliberate to preserve the implemented BUILD-086A/B services without architecture replacement. Future scaling may normalize hot query paths, but no review-readiness blocker remains for the validated scope.
