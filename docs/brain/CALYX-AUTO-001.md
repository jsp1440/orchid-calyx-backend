# CALYX-AUTO-001 — Durable Mission Orchestrator

## Status

IMPLEMENTED + HARDENED ON FEATURE BRANCH / NON-PRODUCTION / EXECUTABLE REPOSITORY ACCEPTANCE PENDING

Branch: `feature/calyx-auto-001-durable-missions`

Current hardened implementation head before this documentation commit: `d0cd85a462a13f03984fe2f1adbaeb27f3fe0be7`.

## Mission

CALYX-AUTO-001 extends the canonical Calyx engineering-program substrate rather than creating a parallel scheduler. `CalyxProgramJob` remains the durable mission record and the existing persistent-program dependency graph remains authoritative for continuation order.

The slice adds the missing execution-control loop:

1. durable queued program mission;
2. governance-aware deterministic priority selection;
3. serialized owner/program admission plus atomic lease claim with worker identity/token/expiry and attempt increment;
4. authoritative registered executor only;
5. post-execution live-lease heartbeat/revalidation;
6. persisted validator decision;
7. retry with validator feedback injected into the next governed assignment, or fail-closed review/dead-letter;
8. validated completion and idempotent Brain completion writeback in the same transaction;
9. dependency release only after that writeback is durable;
10. automatic claim of newly released automatic work until idle, a newly reached governance boundary, finalization cleanup is pending, or the configured cycle budget is exhausted.

## Durable persistence

Additive migration `20260811_calyx_auto_001.sql` adds:

- `calyx_program_validation_events` — durable attempt/disposition/code/feedback/receipt-checksum records;
- `calyx_brain_completion_writebacks` — one idempotent completion record per program job, content-bound by `completion_key`.

The completion payload uses schema `calyx-auto-brain-completion/v1` and records exact program/job identity, executor, input/output checksums, evidence URIs, validation event identity, and permanent non-authority flags.

A divergent second completion key for the same program job fails closed as `BRAIN_COMPLETION_WRITEBACK_DIVERGENCE`.

The writeback is an internal engineering completion ledger. It does not redefine scientific Brain ontology or publication authority.

## Governance-aware selection

`GovernanceAwarePrioritySelector` reads only canonical persisted job inputs. Missions requesting merge, deploy, publication, production mutation, taxonomy activation, credential access, spending, force-push, or branch deletion are owner-only. Cross-repository/external-send/production-migration/schema-activation requests require review.

Governance-bound runnable missions are **held without being consumed or terminalized**:

- status remains `queued`;
- outcome remains unset;
- no lease is issued;
- attempt count is unchanged;
- no Brain completion writeback is created;
- dependent missions are not poisoned with an upstream terminal failure.

If automatic work releases an owner/review-bound child during the same cycle, the hold set is recomputed before the worker declares itself idle. The cycle therefore reports `governance_boundary` immediately and leaves the child resumable for later governed disposition.

Within the automatic subset, lower integer priority executes first, then lower attempt count, persisted scheduler rank, creation order, and mission ID.

## Lease, claim, and concurrency semantics

CALYX-AUTO-001 reuses `PersistentProgramWorker` recovery and heartbeat semantics and adds governed priority before claim. Each claim has worker ID, random lease token, expiry, and attempt generation. Expired leases are recovered before selecting new work. A worker that no longer owns a live lease cannot retry, validate completion, or write Brain completion evidence.

Claim admission is serialized on PostgreSQL by locking the owner's active/running `CalyxProgram` rows in deterministic program-ID order before recomputing the persisted runnable schedule, active jobs, governance ordering, and concurrency admission. The conditional job update remains the final claim guard. This closes the race where concurrent workers could both observe the same pre-claim active set and independently exceed the configured active-job policy.

Execution timeout is prohibited from exceeding the lease, and the lease is heartbeat-verified immediately after executor return before validator disposition/final completion.

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

### Workspace finalization safety

The isolated workspace patch executor intentionally retains its rollback journal until durable mission completion has committed. CALYX-AUTO-001 now treats the database commit as the irreversible orchestration boundary:

- before accepted durable completion, validation/retry/review failures may invoke workspace rollback;
- after job completion + Brain writeback + dependency release have committed, a workspace `finalize()` cleanup failure **must never call rollback**;
- instead the cycle returns `finalization_pending`, keeps the accepted job/writeback durable, and stops before claiming more work;
- the next worker cycle retries idempotent finalization cleanup before any new mission is claimed.

This prevents a split-brain state where durable orchestration says a patch succeeded while a late cleanup exception restores the accepted workspace bytes.

## Persistent worker

`runtime/calyx_auto_worker.py` reuses `ProgramAutonomyPolicy`. It is disabled by default and requires the configured owner before running. `run_forever()` repeatedly invokes bounded cycles with the configured poll interval. Each cycle automatically continues through newly released automatic missions until idle, governance boundary, finalization-pending, error, or budget exhaustion.

## Validation coverage

Committed regression coverage now verifies:

- validator rejection → persisted feedback → second-attempt feedback injection → acceptance;
- accepted completion creates exactly one Brain writeback;
- successful upstream completion releases and automatically executes its automatic dependent mission;
- owner-only merge request remains queued/non-terminal before claim and creates no Brain writeback;
- an owner-only child released by an automatic parent is detected in the same cycle and stops at `governance_boundary` without consuming the child;
- governance-aware mission priority ordering;
- configured active-job limit prevents a second claim while one mission is running;
- expired lease reclaim changes token/worker and increments attempt count;
- post-commit workspace-finalization failure never calls rollback, preserves the accepted job/writeback, stops new work, and retries cleanup on the next cycle without re-executing the mission;
- timeout cannot exceed the lease.

Dependency-light validation recorded before the latest hardening:

- Python syntax compilation for the original new source/test modules: passed;
- selector/validator state assertions: 6/6 passed.

The latest hardened implementation has **not** received executable repository CI because private hosted Actions is again failing before step creation. On head `4c88f145229ba030fc743abb961e9931b4823c79`, dedicated run `31565772832`, job `94017142348`, returned `steps = null`; BUILD-088E, CALYX-AGENT-003, and Workflow Governance failed with the same allocator signature. Those runs executed no checkout, Ruff, tests, migration assertions, or application code and are infrastructure evidence only.

Dedicated workflow `.github/workflows/calyx-auto-001.yml` remains the authoritative acceptance gate. It runs the CALYX-AUTO-001 integration suite plus adjacent autonomous-program worker/persistence tests, Python compile, Ruff, migration invariants, permanent non-authority assertions, and diff hygiene.

Full repository acceptance remains pending a real step-bearing Actions run. Do not substitute the zero-step failures for either a code pass or a code failure.

## Permanent non-authority

CALYX-AUTO-001 grants no automatic merge, deployment, publication, production database mutation, production Knowledge Graph mutation, taxonomy activation, credential access, spending, force push, or branch deletion authority.

The migration is code-only and is not applied to production by this implementation. The persistent orchestrator worker remains disabled by default and is not activated in production by this branch.
