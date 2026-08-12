# CALYX-AUTO-001 — Durable Mission Orchestrator

## Status

IMPLEMENTED ON FEATURE BRANCH / NON-PRODUCTION / FULL REPOSITORY ACCEPTANCE PENDING

Branch: `feature/calyx-auto-001-durable-missions`

## Mission

CALYX-AUTO-001 extends the canonical Calyx engineering-program substrate rather than creating a parallel scheduler. `CalyxProgramJob` remains the durable mission record and the existing persistent-program dependency graph remains authoritative for continuation order.

The slice adds the missing execution-control loop:

1. durable queued program mission;
2. governance-aware priority selection;
3. atomic lease claim with worker identity/token/expiry and attempt increment;
4. authoritative registered executor only;
5. post-execution live-lease heartbeat/revalidation;
6. persisted validator decision;
7. retry with validator feedback injected into the next governed assignment, or fail-closed review/dead-letter;
8. validated completion and idempotent Brain completion writeback in the same transaction;
9. dependency release only after that writeback is durable;
10. automatic claim of the newly released next mission until idle or the configured cycle budget is exhausted.

## Durable persistence

Additive migration `20260811_calyx_auto_001.sql` adds:

- `calyx_program_validation_events` — immutable attempt/disposition/code/feedback/receipt-checksum records;
- `calyx_brain_completion_writebacks` — one idempotent completion record per program job, content-bound by `completion_key`.

The completion payload uses schema `calyx-auto-brain-completion/v1` and records exact program/job identity, executor, input/output checksums, evidence URIs, validation event identity, and permanent non-authority flags.

A divergent second completion key for the same program job fails closed as `BRAIN_COMPLETION_WRITEBACK_DIVERGENCE`.

## Governance-aware selection

`GovernanceAwarePrioritySelector` reads only canonical persisted job inputs. Missions requesting merge, deploy, publication, production mutation, taxonomy activation, credential access, spending, force-push, or branch deletion are owner-only. Cross-repository/external-send/production-migration/schema-activation requests require review. They are held before executor claim and cannot consume an autonomous lease.

Within the automatic subset, lower integer priority executes first, then lower attempt count, persisted scheduler rank, creation order, and mission ID.

This does not weaken the existing concurrency/admission policy.

## Lease and recovery semantics

CALYX-AUTO-001 reuses `PersistentProgramWorker` recovery and heartbeat semantics and adds governed priority before claim. Each claim has worker ID, random lease token, expiry, and attempt generation. Expired leases are recovered before selecting new work. A worker that no longer owns a live lease cannot retry, validate completion, or write Brain completion evidence.

Execution timeout is prohibited from exceeding the lease, and the lease is heartbeat-verified immediately after executor return before validation/finalization begins.

## Validator feedback loop

`MissionReceiptValidator` verifies the authoritative receipt and produces one of:

- `accept`;
- `retry`;
- `review_required`;
- `dead_letter`.

A retry persists exact feedback. The next assignment receives a top-level `validator_feedback` object containing the prior validation code, feedback list, and previous attempt count. Attempts remain bounded by the durable job's `max_attempts`.

## Brain completion writeback and continuation

For an accepted receipt, job completion, Brain writeback, downstream dependency release, and program-status refresh occur in one database transaction. Therefore downstream automatic continuation cannot become runnable if the Brain completion writeback did not persist.

The writeback is an internal durable completion ledger. It is not scientific publication, Candidate Knowledge promotion, taxonomy activation, external Git mutation, deployment, or Knowledge Graph mutation.

## Persistent worker

`runtime/calyx_auto_worker.py` reuses `ProgramAutonomyPolicy`. It is disabled by default and requires the configured owner before running. `run_forever()` repeatedly invokes bounded cycles with the configured poll interval. Each cycle itself automatically continues through newly released missions until idle or budget exhaustion.

## Validation

Committed regression coverage verifies:

- validator rejection → persisted feedback → second-attempt feedback injection → acceptance;
- accepted completion creates exactly one Brain writeback;
- successful upstream completion releases and automatically executes its dependent mission;
- owner-only merge request is held before executor claim and creates no Brain writeback;
- governance-aware mission priority ordering;
- expired lease reclaim changes token/worker and increments attempt count;
- timeout cannot exceed the lease.

Dependency-light local validation completed:

- Python syntax compilation for all new source/test modules: passed;
- selector/validator state assertions: 6/6 passed.

Dedicated workflow `.github/workflows/calyx-auto-001.yml` runs the CALYX-AUTO-001 integration suite plus adjacent autonomous-program worker/persistence tests, Python compile, Ruff, migration invariants, permanent non-authority assertions, and diff hygiene.

Full repository acceptance must be based on an executable GitHub Actions run. A zero-step hosted-runner failure is infrastructure evidence only and is not treated as either pass or failure of the implementation.

## Permanent non-authority

CALYX-AUTO-001 grants no automatic merge, deployment, publication, production database mutation, production Knowledge Graph mutation, taxonomy activation, credential access, spending, force push, or branch deletion authority.

The migration is code-only and is not applied to production by this implementation.
