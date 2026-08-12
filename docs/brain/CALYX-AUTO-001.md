# CALYX-AUTO-001 — Durable Mission Orchestrator

## Status

IMPLEMENTED + HARDENED ON FEATURE BRANCH / NON-PRODUCTION / EXECUTABLE REPOSITORY ACCEPTANCE PENDING

Branch: `feature/calyx-auto-001-durable-missions`
Canonical Brain checkpoint: `Orchid-Continuum-Brain@72c9dc8e8da99e4a2a3ff3d2ebd26bf452aa67b1`.

CALYX-AUTO-001 extends the canonical `CalyxProgramJob`/dependency/lease substrate rather than introducing a second autonomous queue.

## Implemented contract

- Durable mission queue and dependency continuation remain rooted in existing engineering-program tables.
- Governance-aware deterministic priority runs before autonomous claim.
- Governance-bound jobs remain queued/non-terminal and are not leased, attempted, or written back.
- Newly released governance-bound children are re-detected in the same cycle and stop at `governance_boundary`.
- Owner/program claim admission is serialized with deterministic PostgreSQL `FOR UPDATE` locking before active-job/concurrency admission; a conditional job UPDATE remains the final claim guard.
- Each lease carries worker identity, random token, expiry, and bounded attempt count; expired leases are recovered and post-executor heartbeat verifies continued ownership.
- `MissionReceiptValidator` persists accept/retry/review/dead-letter decisions; retry feedback is injected into the next governed assignment.
- Accepted job completion, one content-bound `calyx-auto-brain-completion/v1` writeback, downstream release, and program-status refresh commit together.
- Workspace rollback is permitted before durable acceptance only. After completion/writeback/release commit, `finalize()` failure returns `finalization_pending`, never rolls the accepted patch back, and is retried idempotently before later claims.
- `runtime/calyx_auto_worker.py` is persistent but disabled by default and continues through automatic work only until idle, governance boundary, finalization-pending, error, or cycle budget.

## Governance hardening

Owner-only intents include merge, auto/automatic merge, deploy/automatic deployment, publish/publication/automatic publication, production mutation, taxonomy activation, credential access, spending, force-push, and branch deletion. Review-class intents include cross-repository actions, external sends, production migrations, and schema activation.

The selector recognizes canonical action fields (`action`, `operation`, `requested_action`, action/capability lists) and now also detects clearly enabled direct nested flags such as `{"merge": true}`, `{"automatic_merge": "enabled"}`, or `{"workflow": {"production_migration": true}}`. This closes a pre-claim bypass where a governance-bound request encoded as a direct boolean/string flag could evade the action-list parser. Only explicit enabled scalar flags are interpreted as requests; false flags and evidence metadata such as `{"publication": {"doi": ...}}` remain ordinary data and do not create false holds.

## Persistence

Additive migration `20260811_calyx_auto_001.sql` defines `calyx_program_validation_events` and `calyx_brain_completion_writebacks`. The migration is code-only and unapplied in production.

The Brain writeback is an internal engineering completion ledger. It does not redefine scientific Brain ontology and provides no scientific publication, Candidate Knowledge promotion, taxonomy activation, deployment, merge, production database mutation, or Knowledge Graph mutation authority.

## Regression coverage committed

- validator retry → persisted feedback → next-attempt feedback → acceptance;
- one idempotent completion writeback;
- automatic parent → automatic dependent continuation;
- owner-only mission held queued/non-terminal with zero attempts/writeback;
- direct/nested boolean and enabled-string owner/review action flags cannot bypass the pre-claim governance selector;
- false action flags and publication evidence metadata do not create false governance holds;
- automatic parent → newly released owner-only child → same-cycle governance stop;
- deterministic priority ordering;
- sequential active-job limit enforcement;
- expired lease reclaim/token generation;
- post-commit workspace finalize failure preserving accepted work with zero rollback and no re-execution;
- PostgreSQL 16 two-session contention requiring exactly one successful claim when `max_active_jobs=1`;
- timeout cannot exceed lease.

## Validation boundary

Dependency-light validation recorded before the latest hardening passed Python syntax/AST compilation for the original new modules/tests and 6/6 selector/validator assertions.

The authoritative dedicated workflow provisions PostgreSQL 16 and runs the focused + adjacent autonomous-program suites, PostgreSQL claim contention, Python compile, Ruff, migration invariants, permanent non-authority assertions, and diff hygiene.

Private hosted Actions continue to exhibit zero-step allocator failures (`steps = null`) on feature heads. Such runs execute no PostgreSQL service, checkout, Ruff, tests, migration assertions, or project code. Full executable repository acceptance therefore remains pending; zero-step failure is infrastructure evidence only.

## Permanent boundary

No automatic merge, deployment, publication, production DB/KG mutation, taxonomy activation, credential access, spending, force-push, or branch deletion authority is granted. The persistent worker remains unactivated in production. PR #900 must remain draft/unmerged until executable exact-head acceptance succeeds and a separate governed merge/release disposition is authorized.
