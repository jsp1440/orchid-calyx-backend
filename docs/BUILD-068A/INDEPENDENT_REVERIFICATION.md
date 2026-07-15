# BUILD-068A Independent Re-verification and PostgreSQL Concurrency Proof

Review date: 2026-07-15

Local branch: `feat/scientific-knowledge-graph-completion`

GitHub PR: `jsp1440/orchid-calyx-backend#56`

## 1. Final verdict

**NOT READY TO MERGE**

## 2. Executive summary

The real PostgreSQL single-writer proof passed against a separately initialized,
localhost-only, non-production PostgreSQL 16 cluster. The normal publication
path also accounts for missing `source_pk`/`taxon_pk` values and makes normal-run
health false.

However, BUILD-068A is not merge-ready for three concrete reasons:

1. `BuildOrchestrator.RESUME` discards missing-identifier metrics from completed
   checkpoints when constructing final validation. An executable proof produced
   `top_level_healthy=True` and `cross_domain_healthy=True` while the retained
   checkpoint contained `missing_identifier_rows=1`.
2. The `publication_lock()` context manager does not release its advisory lock
   after a database error aborts the transaction. Its unlock query fails with
   `InFailedSqlTransaction`; a competing session remains blocked until the
   original connection is closed.
3. PR #56 still points to head `e1df5e99f63fb64e0edbd99ea8f92fb696e2c131`.
   All BUILD-068A corrections and this report are uncommitted local changes, so
   the pull request being considered for merge does not contain the corrections.

The first original blocker is corrected for the actual BUILD-068 driver and
`publish_to_production`, but one advertised context-manager failure path is not.
The second original blocker is corrected for normal execution but remains open
for generic checkpoint/resume execution.

## 3. Advisory-lock findings

### Guarantees verified

- The key is deterministic: `_publication_lock_key(schema)` hashes a fixed
  namespace plus schema with SHA-256 and converts the first 64 bits to a signed
  PostgreSQL bigint (`repository.py:31`).
- The key is schema-scoped and both production entry points construct the same
  repository type with the same schema.
- `b068.py` acquires before entering its `publish`/`idempotency` phase branches,
  and therefore before baseline reads and publisher work (`b068.py:99-103`).
- `publish_to_production` acquires before `BuildOrchestrator.run`
  (`production_publish.py:51`).
- `pg_try_advisory_lock` is fail-fast and raises an explicit
  `PublicationLockError` (`repository.py:445-461`).
- The bigint API used is session-level, not transaction-level. The isolated
  PostgreSQL contention test committed while holding the lock, and the second
  connection still failed to acquire it.
- The BUILD-068 driver holds a dedicated lock session across writer batch and
  domain commits, so those commits do not release the guard.
- Normal explicit unlock, successful close, and connection-lifecycle release
  worked in the isolated tests.
- The two actual production entry points close their repositories in `finally`
  paths. No additional non-test production publication entry point was found.

### Defect: aborted-transaction context exit

`publication_lock()` calls `release_publication_lock()` directly in `finally`.
That method issues `SELECT pg_advisory_unlock(...)` on the same connection. If a
database error has put that transaction into the aborted state, PostgreSQL
rejects the unlock query.

Executable isolated-cluster result:

```text
context_exit_error=InFailedSqlTransaction
lock_still_held_after_context_exit=True
close_error=InFailedSqlTransaction
acquired_after_connection_close=True
```

Thus connection close is an effective final guarantee, but context exit alone
is not. The existing exception test raises a Python `RuntimeError` without
aborting the PostgreSQL transaction and does not cover this case.

## 4. Missing-identifier findings

### Correct behavior verified

- Every built-in adapter declares `("source_pk", "taxon_pk")` as required.
- `publish_domain` materializes each input batch and validates rows before
  calling the adapter.
- `None` and `""` are rejected for either identifier; `0` remains a valid ID.
- Direct built-in adapter invocation raises on malformed rows instead of
  silently skipping.
- `source_rows` counts all rows. `missing_identifier_rows` counts a malformed
  row once, while `missing_identifier_counts` correctly counts each missing
  field (including both fields on one row).
- Rejected examples contain only domain, batch-relative row index, and missing
  field names. They do not include source payload data and are capped at ten.
- Normal per-domain outcomes, aggregate totals, checkpoints, coverage reports,
  BUILD-068 phase data, and idempotency data expose rejection information.
- `validate_graph` adds every rejected row to `total_problems`; normal
  cross-domain and top-level health therefore become false. Zero rejected rows
  preserve successful behavior.

### Blocking defect: resume loses checkpointed rejection metrics

On resume, completed domains become newly constructed `STATUS_SKIPPED`
`DomainOutcome` objects (`orchestrator.py:154-163`). Those objects do not restore
the completed checkpoint's `missing_identifier_rows`, counts, or examples.
Final validation and totals sum only these current outcomes
(`orchestrator.py:176-185`, `330-334`).

Executable proof:

```text
top_level_healthy=True
cross_domain_healthy=True
reported_missing_identifier_rows=0
checkpoint_missing_identifier_rows=1
outcome_status=skipped
```

This violates the requirement that any authorized row rejected for a missing
identifier must prevent healthy build status, including after checkpoint/resume.
The BUILD-068 standalone validation phase rehydrates its JSON checkpoints and
does not share this specific defect, but the reusable production helper's
`RESUME` path does.

## 5. PostgreSQL proof

### Non-production classification

A new ephemeral cluster was initialized specifically for this review:

- PostgreSQL `16.11`
- loopback only: `127.0.0.1:55432`
- role: `build068a_test`
- database: `build068a_verification`
- data directory: `.codex-build068a-pg` inside the local workspace

This was distinct from the machine's existing PostgreSQL service and from every
production credential. No production `DATABASE_URL` was configured or used.
After testing, the ephemeral server was stopped, the listener was verified
absent, and the entire temporary cluster directory was removed.

### Executed PostgreSQL tests

- `tests/test_build_067_pg_writer.py`: **15 passed**.
- Explicit lock subset: **2 passed**:
  - `test_second_concurrent_publisher_fails_fast_and_lock_releases`
  - `test_publication_lock_releases_after_exception`
- Post-test cleanup query: **0** `kg_w_test_%` schemas and **0** objects in such
  schemas remained.

The contention test proved fail-fast behavior across two real connections and
lock survival across `commit()`. The exception test proved release after a
non-database Python exception. The additional aborted-transaction proof exposed
the context-manager defect documented above.

## 6. Test results

- Targeted Knowledge Graph suite: **not rerun after the mandatory stop condition
  was reached**. The earlier BUILD-068A run reported 118 passed / 14 skipped,
  but those counts are not presented as independent re-verification evidence.
- PostgreSQL isolated-schema suite: **15 passed, 0 failed, 0 skipped**.
- Explicit PostgreSQL lock subset: **2 passed, 0 failed, 0 skipped**.
- Full repository suite: **not rerun after the mandatory stop condition was
  reached**. The earlier BUILD-068A run reported 489 passed / 1 failed / 14
  skipped.

Stopping at discovery of a remaining original blocker follows the supplied
STOP CONDITIONS.

## 7. Existing cache failure determination

**Pre-existing and unrelated to BUILD-068A.**

Evidence:

- The failure is in `runtime/scientific_intelligence/cache.py` and
  `tests/test_build_062_scientific_intelligence.py`.
- Both files are byte-for-byte unchanged from `HEAD` (`git diff --quiet` exit 0).
- Neither file appears in the BUILD-068A diff.
- The implementation expires only when `time.monotonic() - stored_at > ttl`.
  With `ttl=0`, an immediate read may have an exactly zero measured delta, so
  the existing test's expectation is not guaranteed by that predicate.

BUILD-068A did not cause this behavior. It was not fixed because it is outside
the authorized scope.

## 8. Remaining blockers

1. Restore completed checkpoint rejection metrics into resume outcomes/final
   validation so resume cannot report a false healthy result.
2. Make advisory-lock context cleanup safe after an aborted database transaction
   (or remove/limit the unsupported context-manager guarantee) and add a real
   database-error regression test.
3. Commit the corrected BUILD-068A changes and update PR #56; the current remote
   PR head contains none of them.
4. Re-run the independent targeted and full regression suites after those
   corrections, plus the isolated PostgreSQL suite.

## 9. Scope confirmation

- No deployment performed.
- No production reads or writes performed during this verification.
- No production migration executed.
- No migration executed against the ephemeral test cluster.
- No unauthorized domain publication performed.
- PR #56 remains open and unmerged.
- BUILD-069 was not started.
- The only database writes were isolated test schemas in the ephemeral local
  cluster; all were removed with the cluster.
- No implementation source file was changed by this independent verification.

## 10. Merge recommendation

**Do not merge PR #56.** Correct the resume aggregation and aborted-transaction
lock cleanup defects, commit/push BUILD-068A to the PR branch, and repeat this
independent re-verification with the real isolated PostgreSQL suite.
