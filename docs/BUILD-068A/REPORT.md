# BUILD-068A Targeted Concurrency & Validation Corrections

## Outcome

The two blocking findings from the BUILD-068 independent review are corrected
without redesigning the graph architecture or starting BUILD-069.

## 1. Single-writer safety

- Added a deterministic, schema-scoped PostgreSQL session advisory lock.
- `publish` and `idempotency` acquire the lock before reading the baseline or
  invoking any publisher work.
- The reusable production publication helper acquires the same lock.
- A concurrent second publisher fails fast with a clear
  `PublicationLockError` message.
- The session lock survives batch/domain commits and is explicitly released on
  success, failure, and context exit; PostgreSQL connection close remains the
  final release guarantee.
- Checkpoint/resume and idempotent publication behavior are unchanged.

## 2. Missing-identifier row accounting

- Built-in adapters declare `source_pk` and `taxon_pk` as required identifiers.
- `publish_domain` validates rows before adapter execution and records:
  source-row count, rejected-row count, per-identifier counts, and bounded
  examples.
- Direct invocation of a built-in adapter with unvalidated missing identifiers
  raises instead of silently skipping.
- Per-domain outcomes, totals, checkpoints, coverage reports, BUILD-068 result
  data, and idempotency data now expose rejected rows.
- `validate_graph` accepts publication input metrics and counts every rejected
  missing-identifier row as a problem. Consequently, both cross-domain and
  top-level build health are false whenever such a row exists.

## Files changed

- `docs/BUILD-068/b068.py`
- `docs/BUILD-068/RUNBOOK.md`
- `docs/BUILD-068A/REPORT.md`
- `runtime/knowledge_graph/__init__.py`
- `runtime/knowledge_graph/adapters.py`
- `runtime/knowledge_graph/orchestrator.py`
- `runtime/knowledge_graph/production_publish.py`
- `runtime/knowledge_graph/publisher.py`
- `runtime/knowledge_graph/reporting.py`
- `runtime/knowledge_graph/repository.py`
- `runtime/knowledge_graph/validation.py`
- `tests/test_build_067_pg_writer.py`
- `tests/test_knowledge_graph_orchestrator.py`
- `tests/test_source_registry.py`

## Test results

- Focused and related Knowledge Graph suites: **118 passed, 14 skipped**.
- The 14 skips are PostgreSQL isolated-schema tests because `DATABASE_URL` is
  not configured in this workspace. They include the two new real-PostgreSQL
  concurrency/release tests; no production database was accessed.
- Full repository suite: **489 passed, 1 failed, 14 skipped**.
- The sole full-suite failure is the pre-existing, out-of-scope BUILD-062 cache
  assertion `test_cache_expiry` (`ttl=0` returns the just-written value). It
  reproduces in isolation and no BUILD-068A file participates in that codepath.
- Python compilation of the changed BUILD-068 driver and Knowledge Graph
  modules passed.

## Updated merge recommendation

**READY FOR INDEPENDENT RE-VERIFICATION; DO NOT MERGE YET.**

The two code-level blockers are addressed and all executable targeted tests
pass. Before changing the recommendation to merge, run the isolated-schema
PostgreSQL tests with a non-production `DATABASE_URL` so the real advisory-lock
contention and exception-release paths execute, then repeat the independent
review against the resulting commit/PR diff.

## Scope confirmation

- No deployment performed.
- No production writes performed.
- No migration executed.
- PR #56 not merged.
- BUILD-069 not started.
