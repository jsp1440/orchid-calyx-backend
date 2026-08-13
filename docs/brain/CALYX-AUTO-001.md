# CALYX-AUTO-001 — Durable Mission Orchestrator

## Status

IMPLEMENTED + EXECUTABLY HARDENED ON FEATURE BRANCH / NON-PRODUCTION / ONE GOVERNANCE-NORMALIZATION BLOCKER REMAINS

Branch: `feature/calyx-auto-001-current-main-r3`  
Pull request: #941  
Last updated: 2026-08-13.

CALYX-AUTO-001 extends the canonical `CalyxProgramJob`/dependency/lease substrate rather than introducing a second autonomous queue.

## Implemented contract

- Durable mission queue and dependency continuation remain rooted in existing engineering-program tables.
- Governance-aware deterministic priority runs before autonomous claim.
- Governance-bound jobs remain queued/non-terminal and are not leased, attempted, or written back.
- Runnable jobs whose role has no registered authoritative executor are held rather than being misreported as idle.
- Invalid persisted scheduler state fails closed as `scheduler_invalid`; scheduler-integrity errors are not converted to a false idle result.
- Newly released governance-bound children are re-detected in the same cycle and stop at `governance_boundary`.
- Owner/program claim admission is serialized with deterministic PostgreSQL `FOR UPDATE` locking before active-job/concurrency admission; a conditional job UPDATE remains the final claim guard.
- Each lease carries worker identity, random token, expiry, and bounded attempt count; expired leases are recovered and post-executor heartbeat verifies continued ownership.
- Every executor receipt is bound to the exact dispatched assignment before heartbeat, validator persistence, retry/review disposition, completion, or Brain writeback.
- `MissionReceiptValidator` persists accept/retry/review/dead-letter decisions only after receipt binding succeeds; retry feedback is injected into the next governed assignment.
- Accepted job completion, one content-bound `calyx-auto-brain-completion/v1` writeback, downstream release, and program-status refresh commit together.
- Workspace rollback is permitted before durable acceptance only. After completion/writeback/release commit, `finalize()` failure returns `finalization_pending`, never rolls accepted work back, and is retried idempotently before later claims.
- `runtime/calyx_auto_worker.py` is persistent but disabled by default and continues through automatic work only until idle, governance boundary, scheduler-invalid, finalization-pending, error, or cycle budget.

## Hardening completed during executable validation

Executable GitHub Actions became available again, replacing the earlier zero-step infrastructure condition with real PostgreSQL-backed test evidence. Validation then exposed and corrected several shared defects rather than treating red CI as an infrastructure excuse.

### Validation import boundary

The dedicated workflow did not set the repository Python import root, so pytest collection failed before CALYX-AUTO logic executed. `PYTHONPATH=.` is now explicit in the workflow.

### Dependency-free program contract

`PersistentProgramRepository.create_program()` previously required a `dependencies` argument even for one-job or otherwise dependency-free programs. Existing callers correctly model an empty graph, so `dependencies` now defaults to an empty iterable rather than forcing redundant caller boilerplate.

### Cross-dialect lease timestamp semantics

PostgreSQL returns timezone-aware lease timestamps while SQLite drops timezone metadata even with timezone-aware SQLAlchemy columns. That caused valid accepted-work paths in the SQLite harness to fail when comparing lease expiry with aware UTC clocks. `CalyxProgramJob.lease_expires_at` now uses a UTC-normalizing SQLAlchemy type that restores UTC awareness for dialects returning naive values without weakening expiry checks. PostgreSQL continues to preserve UTC-aware semantics.

This single portability correction restored validator retry/continuation, newly released governance-child detection, priority execution, and post-commit finalization behavior.

### PostgreSQL concurrency fixture integrity

The PostgreSQL contention regression creates only a bounded table subset. Its program-job table references `calyx_orchestrator_jobs`, but that referenced base table was absent from the test fixture. The fixture now includes `CalyxJob.__table__`, making a fresh database self-contained without altering the production foreign key or schema contract.

### Comprehensive validation workflow

The final workflow validates `program_models.py` and `program_repository.py` in path triggers, compile, and Ruff. Independent Ruff, migration-invariant, permanent-non-authority, and diff-hygiene checks run even when the focused pytest step fails, so one failing regression no longer hides unrelated validation results. The temporary feature-branch push trigger used to force executable validation has been removed; the workflow is back to its intended PR and `main` scopes.

## Governance normalization status

The action-token normalizer already canonicalizes case, spaces, and hyphens, so equivalent spellings such as `force-push`, `Production Database Mutation`, `taxonomy-activation`, `production-migration`, and `schema activation` fail closed correctly.

One tested semantic synonym remains unresolved: `{"action": "branch deletion"}` normalizes syntactically to `branch_deletion`, while the owner-only canonical token is `branch_delete`. The exact intended hardening is a semantic alias from `branch_deletion` to `branch_delete` before governance comparison. The repository connector blocked that code write because it directly changes branch-deletion authority. This is therefore retained as an explicit governance/tool boundary rather than bypassed, weakened, or hidden by removing the regression.

The regression remains intentionally red until that governed normalization change can be authorized/applied through an allowed path.

## Executable validation history

The dedicated PostgreSQL workflow now runs on real GitHub hosted runners:

1. Original executable run: compile succeeded; pytest collection exposed missing `PYTHONPATH`.
2. After import repair: 35 passed / 13 failed, revealing real implementation and fixture defects.
3. After dependency-free program contract repair: 42 passed / 6 failed.
4. After UTC lease normalization and self-contained PostgreSQL FK fixture: **47 passed / 1 failed**.
5. The sole remaining failure is the explicit `branch deletion` governance-alias regression described above.

The 47 passing tests include validator feedback/retry, dependency continuation, owner/review holds, unsupported-role hold behavior, scheduler-integrity handling, receipt identity/checksum binding, deterministic priority, lease reclaim, post-commit finalization recovery, PostgreSQL two-worker active-limit contention, and adjacent autonomous-program persistence/worker regressions.

## Persistence

Additive migration `20260811_calyx_auto_001.sql` defines `calyx_program_validation_events` and `calyx_brain_completion_writebacks`. The migration remains code-only and unapplied in production.

The Brain writeback is an internal engineering completion ledger. It does not redefine scientific Brain ontology and provides no scientific publication, Candidate Knowledge promotion, taxonomy activation, deployment, merge, production database mutation, or Knowledge Graph mutation authority.

## Permanent boundary

No automatic merge, deployment, publication, production DB/KG mutation, taxonomy activation, credential access, spending, force-push, or branch deletion authority is granted. The persistent worker remains unactivated in production.

PR #941 must remain unmerged while the governance alias regression is unresolved. Even after executable acceptance is fully green, merge and any migration/worker production activation remain separate owner-governed decisions.
