# Phase 10 — paired locally verified release candidate

## Dependency order and isolation

Fresh Calyx branch: `replit/p0-phase10-release-candidate-calyx`.
Fresh Brain branch: `replit/p0-phase10-release-candidate-brain`.
No existing PR branch was edited, reset, rebased or merged.

The exact reused source chain is:

1. Calyx #1789: `e0afc3bb1125f60083b2fb0ec43655a2d43989c7`
   (lifecycle and truthful terminal accounting).
2. Calyx #1790: `2a2c8e4af54a8fe89f10e6d7bfd5686e96e0f2fe`
   (admission/replay plus scheduler convergence from #1788).
3. Calyx #1791: `50389c1e2cf17976b51277273608ac576b3a125c`
   (Plan #9 capability endpoint).
4. Brain #223: `ff1d7774b60d5c4a27c15543d255ab1c1f2fa26f`
   (required reasoning-contract companion).
5. Brain #224: `fd535c54d8daa30e87605a0c772aa32d306f19dc`
   (real verification packet producer).
6. Brain #225: `0ed72404add96f24e8a0c6afd9359b690d26a78a`
   (Plan #9 conditional compatibility preflight).

The assignment calls #1790 the completed API compatibility repair. Its admission
repair is included, but the completed Plan #9 endpoint is actually in #1791,
which is included as well. No dependency was omitted because of that label.

#1788 is pinned at `a1e1744a9ca1878466f10bf0e7257350947af09c`.
Its two repaired scheduler workflows, timer harness, scheduler-concurrency test
and productive-proof test were compared byte-for-byte with this candidate and
match. Earlier scheduler patches were already cherry-picked into #1790.
Ancestry checks confirm the remaining predecessor heads are included.
No redundant cherry-pick, replacement scheduler or new service was necessary.

## Actual integration work and verification

Added `tests/test_phase10_paired_release_candidate.py`, committed at checkpoint
`eeb8e02`. It loads the actual current Brain producer/preflight and calls the
actual Calyx HTTP routes against a dedicated PostgreSQL schema.

All five source-check pathways (Lexicon, Literature, Research Station, Atlas,
University) are submitted twice. The database contains exactly five programs
and ten jobs, not duplicates. The existing production `run_forever` owns the
cycle loop; the test never calls individual cycles manually.

Observed claims use ten distinct job IDs and ten distinct hashed lease tokens,
with the expected worker and unexpired leases. Real existing evidence/static
executors complete ten jobs, persist receipts/timestamps, settle the programs,
and release the leases. A simulated first-cycle storage interruption exercises
the worker's existing error catch; it subsequently continues and completes work.

This focused test accelerates the injected sleeper while preserving the validated
15-second policy value. It is not evidence of production wall-clock cadence.
Authentication is fixture-supplied; source snapshots and scientific identifiers
are disposable fixtures, not live science or deployed authentication evidence.

## Combined focused results

- Calyx: **128 passed, 3 skipped, 1 deselected**, including the new paired
  PostgreSQL loop test, three PostgreSQL admission/claim races, actual HTTP
  handoff, lifecycle, accounting, worker, canonical admission, scheduler,
  workflow and productive-proof contracts.
- Brain: **81 passed**, including old/new/future capability behavior, producer,
  reasoning-envelope, lane and resource-governor tests.
- Changed-file Ruff E4/E7/E9/F and whitespace checks passed.
- No runtime mismatch or source conflict was found; no speculative runtime
  correction was made. The implementation is the isolated dependency composition
  plus new combined acceptance coverage and fresh runtime evidence.

These results are from this paired candidate, not a sum of prior PR claims.
The three skipped checks and one app-import route exclusion are not called green.
The required HTTP/intake path has separate actual-router coverage.

## Fresh real timer and recovery evidence

Both proofs use a disposable loopback PostgreSQL cluster, separate schemas and
real supervisor subprocesses running the existing worker's own timer.
The harness never invokes individual cycles. Source runtime is the exact Calyx
`50389c1` tree; subsequent candidate changes are tests and evidence only.

`artifacts/p0-phase10-productive-timer-proof.json`:

- PASS; **10 cycles, 10 completed jobs**, nine assertions, **146.74 seconds**.
- Unique claims, live owned leases, durable completions, no duplicates.
- Real normal timer cadence, no outbound network calls.

`artifacts/p0-phase10-fault-recovery-proof.json`:

- PASS; **28 assertions**, **208.19 seconds**.
- Two supervisors ran **14/13 cycles** and completed **9/7 jobs**.
- Killed-worker lease recovery, refusal of duplicate leases, one-winner
  concurrent claim, stale-token fencing, durable receipt/ledger agreement.
- Simulated provider errors do not stall other work; failed attempts follow
  existing retry/backoff/dead-letter rules and do not become false completions.
- Mid-run enqueued work completes autonomously; loops survive realistic errors.
- No outbound network calls; external model providers are fake.

The proof workload is synthetic probe work. The separate paired PostgreSQL
source-check test verifies real producer/preflight/admission/executor composition.
Neither is proof of scientific output or live hosted autonomy.

## Reproduction

Use the explicit current Brain source in `OC_BRAIN_CONTRACT_ROOT`, current
frontend contract source in `OC_FRONTEND_CONTRACT_ROOT`, `NO_API=true`, a local
SQLite `DATABASE_URL` for ordinary tests and a dedicated disposable
`OC_ADMISSION_TEST_DSN=postgresql://oc_test@127.0.0.1:55439/postgres` for the
opt-in PostgreSQL fixtures. Those fixtures never select PostgreSQL from
`DATABASE_URL` and reject other hosts/ports.

```sh
python -m pytest -q tests/test_phase10_paired_release_candidate.py \
  tests/test_brain_postgres_admission.py tests/test_brain_production_handoff.py \
  tests/test_brain_cross_repository_contracts.py tests/test_brain_admission_replay.py \
  tests/test_submission_capabilities.py tests/test_brain_module_lifecycle_contracts.py \
  tests/test_brain_cycle_terminal_accounting.py tests/test_calyx_autonomous_program_core.py \
  tests/test_calyx_autonomous_program_cycle.py tests/test_calyx_program_claim_races.py \
  tests/test_canonical_brain_build_queue.py tests/test_canonical_brain_scheduler_bridge.py \
  tests/test_oc_scheduler_concurrency.py tests/test_orchid_swarm_v4_workflow_contract.py \
  tests/test_orchid_swarm_parallel_executor_contract.py \
  tests/test_orchid_swarm_edit_lane_wiring.py tests/test_productive_timer_proof.py \
  -k 'not route_is_mounted'
```

Brain focused commands are the compatibility, verification producer, reasoning,
envelope, resource-governor and lane test modules already in this candidate.
Fresh timer-proof artifacts retain the exact proof parameters and assertions.

## Authorization, budget and release decision

Existing admission constitution, owner authentication, provider role restrictions,
cycle/lease/capacity limits and resource-policy controls are preserved.
Verification admission grants no paid-provider, mutation, merge, deploy or
scientific publication authority. Older receivers safely reject required missing
features; legacy submissions bypass discovery; future compatible receivers work.

No paid external providers, hosted Actions, production DB operations, merges,
deployment, purchased credits, overage enablement or billing changes occurred.
This phase's actual Replit spending is unavailable. The Git checkpoint is
explicit; the Agent cannot certify an automatically metered $10 stop point.
Do not treat account-period spending as the phase's cost.

**GO:** paired local release candidate for independent exact-head review and
subsequently authorized controlled recovery integration.
**NO-GO:** production deployment, unattended scientific operations or a claim
that the autonomous engine is operational.

Remaining gates: independent paired review; approved source snapshots and
automatic authenticated discovery-to-submission transport; deployed-version and
hosted scheduler activation verification; real authentication/provider availability
and actual spending observation before any separately authorized provider lane.
All source-check/probe simulations must remain distinguished from science.

Before integration, rollback is leaving/closing only these new drafts. Original
PRs are preserved. After a separately authorized integration, stop new submission
transport first and review any paired revert; preserve existing programs/jobs.
No database schema reversal or destructive branch reset is needed.
