# BUILD-068B Targeted Resume, Lock-Release, and PR-Integration Corrections

## 1. Final verdict

**READY FOR INDEPENDENT RE-VERIFICATION**

## 2. Executive summary

All three BUILD-068A re-verification blockers were corrected. Completed-domain
checkpoint metrics now survive resume and participate in domain outcomes,
totals, reporting, and validation. Advisory-lock cleanup now recovers an
aborted PostgreSQL transaction without committing work or masking the original
database exception. The complete BUILD-068A/068B correction set was committed
and pushed to the existing PR #56 feature branch; the PR remains open and
unmerged.

## 3. Resume correction

### Root cause

`BuildOrchestrator.RESUME` previously created fresh zero-valued
`STATUS_SKIPPED` outcomes for completed domains. Final aggregation therefore
forgot rejection metrics retained by checkpoints.

### Implementation

The resume path now loads each completed checkpoint and reconstructs its
`DomainOutcome` without fetching or republishing source rows. It restores:

- source rows / rows processed
- nodes and edges written
- existing-node and existing-edge skips
- invalid count
- missing-identifier row count
- per-identifier counts
- at most ten missing-identifier examples
- batch count
- prior checkpoint validation

Serialized domain results and aggregate totals now include the `source_rows`
alias while preserving `rows_processed`. The BUILD-068 checkpoint writer also
persists `source_rows` explicitly.

### Validation and executable evidence

Four focused resume tests prove:

- one restored rejection makes cross-domain and top-level health false
- three malformed rows remain three rejected rows while the two missing fields
  are independently counted twice each
- a clean checkpoint remains healthy
- restored and newly executed domain metrics aggregate consistently

Completed domains remain skipped and are not republished.

## 4. Advisory-lock correction

### Root cause and transaction behavior

A genuine PostgreSQL error leaves the transaction in `INERROR`. The earlier
context cleanup attempted `pg_advisory_unlock` in that failed transaction, so
PostgreSQL raised `InFailedSqlTransaction` and retained the session lock.

### Cleanup strategy

On an exceptional `publication_lock()` exit, the repository now rolls back the
current uncommitted publication transaction before unlocking. It never commits
caller work. If rollback/unlock cleanup itself fails, the connection-close
fallback releases the session lock. A bare re-raise preserves the original
publication exception rather than replacing it with a cleanup exception.

Normal exit still unlocks directly. Session-level locking continues across
ordinary commits, concurrent acquisition remains fail-fast, and `close()` now
recovers an aborted transaction before retrying unlock while retaining session
close as the final guarantee. This repository does not use a connection pool;
closed connections are cleared and cannot return to reuse holding the lock.

### Real PostgreSQL evidence

The mandatory database-error test executed `SELECT 1/0`, confirmed transaction
status `INERROR`, observed the original `psycopg.errors.DivisionByZero`, exited
the lock context, and proved a second live session could acquire the same lock.
Separate tests proved commit survival/contention, normal context release,
Python-exception release, and connection-close fallback.

## 5. PostgreSQL environment classification

- Version: PostgreSQL 16.11, 64-bit
- Interface: loopback-only `127.0.0.1:55432`
- Database: `build068b_verification`
- Role: dedicated local test role `build068b_test`
- Data location: temporary `.codex-build068b-pg` directory inside the workspace

This cluster was initialized solely for BUILD-068B, was separate from the
machine's installed PostgreSQL service, used no production credentials, and
contained only isolated test schemas. Post-test queries reported zero remaining
`kg_w_test_%` schemas and objects. The server was stopped, the listener was
verified absent, and the complete temporary data directory was removed.

## 6. Test results

- Focused BUILD-068B regressions: **9 passed, 0 failed, 0 skipped**
- Targeted/related Knowledge Graph suite: **139 passed, 0 failed, 0 skipped**
- Real PostgreSQL isolated-schema writer suite: **18 passed, 0 failed, 0 skipped**
- Full repository suite in its normal no-database environment:
  **493 passed, 1 failed, 17 skipped**

Explicit PostgreSQL results:

- concurrent contention and lock survival across commit: passed
- Python exception release: passed
- genuine transaction-aborting database-error release: passed
- successful context exit release: passed
- connection-close fallback: passed

The full-suite database-injected run was diagnostic only: tests that explicitly
expect no database or require the complete Mission Control schema fail when
pointed at the intentionally empty isolated graph database. The authoritative
full-suite count above uses the repository's normal environment; PostgreSQL
coverage is reported separately by the complete isolated writer suite.

## 7. Existing cache failure determination

**PRE-EXISTING AND UNRELATED**

The sole normal-environment full-suite failure remains
`tests/test_build_062_scientific_intelligence.py::test_cache_expiry`.
BUILD-068B does not modify that test, `runtime/scientific_intelligence/cache.py`,
or any code in its execution path. Both files are unchanged from the prior
remote head. The existing implementation expires on `age > ttl`; an immediate
read with `ttl=0` can measure zero age and return the value. This unrelated
failure was not fixed.

## 8. Git and PR state

- Local branch: `feat/scientific-knowledge-graph-completion`
- Correction commit: `ab9d89645bb72d450be18c9b2cd83164f2e87508`
- Prior remote PR head: `e1df5e99f63fb64e0edbd99ea8f92fb696e2c131`
- Verified remote PR head containing corrections:
  `ab9d89645bb72d450be18c9b2cd83164f2e87508`
- PR #56 state at verification: open, unmerged, merge state clean
- Local and remote correction branches: synchronized at correction verification

This report is published as a documentation-only follow-up commit after the
correction commit. Final post-report synchronization and head SHA are recorded
in the task handoff because a commit cannot embed its own SHA.

## 9. Scope confirmation

- No deployment performed.
- No production writes performed.
- No production migrations performed.
- No migration created or executed for BUILD-068B.
- No unauthorized domain publication performed.
- Authorized six-domain scope remained unchanged.
- PR #56 was not merged.
- BUILD-069 was not started.
- No production credentials, local database files, `.env` secrets, or temporary
  test artifacts were committed.

## 10. Final recommendation

BUILD-068B is ready for a fresh independent re-verification. This correction
build does not recommend merging directly; PR #56 should remain unmerged until
that independent review confirms the pushed corrections.
