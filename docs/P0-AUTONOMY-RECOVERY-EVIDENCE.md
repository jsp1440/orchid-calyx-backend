# P0 autonomy recovery: bounded implementation evidence

## Source and branch boundaries

- Backend base: `oc-autonomous-integration`, exact initial checkout
  `4a2b48dd05d7f578eee20aff248c923a585eceb8`.
- Feature branch: `replit/p0-autonomy-recovery-20261007`.
- Backend PR #1767 was already merged into integration when inspected.
- Current frontend integration and private Brain `main` were obtained from
  GitHub. Neither was changed. Active PR branches were not modified.

## Repairs and regression evidence

1. `3a6e9ca`: isolate the dispatch-only legacy redirect's concurrency group.
   The added regression failed before the fix (one failure, three passes).
   After the fix, the concurrency and existing v4 contract tests passed (18).
2. `37acb45`: route a default-branch scheduled pulse to integration before any
   planning or lease writes. The edit worker already refuses non-integration
   refs, while the old plan could claim work from a scheduled `main` run.
   Dispatch-only scheduled runs now use a separate concurrency group.
   The three new routing assertions failed before the correction. Afterwards
   48 scheduler, parallel-worker, edit-lane, and v4 contract tests passed.
   Dispatch tests execute real bash with a fake GitHub CLI; rejection exits 9
   and creates no success summary.
3. `c92d4f0`: extend the existing isolated timer harness with a `productive`
   scenario. It requires one supervisor, one job per cycle, and at least ten
   cycles. Evidence rejects idle cycles, reused lease fingerprints, absent
   persistence, and reordered completion. Six focused positive/negative
   evidence tests passed. This extends testing, not production authority.

Ruff check, Ruff format check, and `git diff --check` passed for the completed
repair. No lease, governor, retry, owner-gate or provider policy was relaxed.

## Disposable PostgreSQL timer proof

`artifacts/p0-autonomy-timer-proof.json` is the actual output from the existing
`scripts/oc_program_autonomy_timer_proof.py`, not a fabricated receipt.

Command (local disposable database only):

```sh
env -u PGHOST DATABASE_URL=postgresql://oc_test@127.0.0.1:55439/postgres \
python3 -B scripts/oc_program_autonomy_timer_proof.py \
  --dsn postgresql://oc_test@127.0.0.1:55439/postgres \
  --supervisors 2 --target-cycles 10 --deadline-seconds 420 \
  --require-defect-fixes --output artifacts/p0-autonomy-timer-proof.json
```

Result: PASS, 28 assertions, zero failed assertions, no detected known defects,
199.17 seconds. Supervisors emitted 14 and 13 consecutive autonomous timer
cycles, completing 9 and 7 jobs respectively. The harness exercised real
supervisor subprocesses, PostgreSQL persistence, claims, duplicate-lease
rejection, SIGKILL/recovery, stale-token fencing, retry/backoff, dead-letter,
mid-run enqueue and duplicate-execution detection. External providers were
simulated; a network guard prevented external calls.

The proof ran at the first repair commit; the second repair changes workflow
routing and tests only, not the runtime code exercised by this proof.

## Ten consecutive productive cycles

`artifacts/p0-productive-timer-proof.json` records the stricter proof at
`c92d4f0`. Command:

```sh
env -u PGHOST DATABASE_URL=postgresql://oc_test@127.0.0.1:55439/postgres \
python3 -B scripts/oc_program_autonomy_timer_proof.py \
  --dsn postgresql://oc_test@127.0.0.1:55439/postgres \
  --scenario productive --supervisors 1 --max-jobs-per-cycle 1 \
  --target-cycles 10 --deadline-seconds 220 \
  --output artifacts/p0-productive-timer-proof.json
```

Result: PASS, nine assertions, 148.82 seconds, exactly ten consecutive timer
cycles and ten completed jobs. A pre-seeded dependency chain supplies the
work. The real supervisor automatically claims, executes and completes one
job per cycle; releasing the next dependency replenishes eligibility.
The harness never invokes the cycle and never manually triggers individual
tasks. Each executor start reads the actual persisted live owned lease,
records a SHA-256 fingerprint (never the token), and final verification checks
durable delivered state, released leases, unique jobs, ordered results and
one execution per job. The executor is the existing real AutonomyProbeExecutor
with proof-only ledger instrumentation; this is useful acceptance-test work,
not a scientific product result or proof of live external-service integration.

The separate full scenario above provides duplicate-lease rejection,
worker-recovery, retries and dead-letter evidence.

## Additional focused checks

34 program-cycle, persisted-scheduler, canonical Brain scheduler-bridge and
Brain pulse tests passed (one route-mount test deselected while local runtime
dependencies were incomplete).

A wider Brain/worker/claim/wave run initially recorded 157 passes and one
environment failure: the Replit workspace's older Starlette TestClient passes
an `app` argument removed by the installed HTTPX. After aligning the installed
FastAPI/Starlette with the current GitHub backend requirements, the Brain API
and focused timer harness checks passed: 20 passed, two long-running cases
deselected. No GitHub backend dependency change was necessary. The entire
repository test suite was not run.

## Exact remaining blockers and limitations

- GitHub rejected the branch push because the existing Personal Access Token
  lacks `workflow` scope for `.github/workflows/*`. No remote branch or PR was
  created. Rejected upload is not a published implementation.
- The full fault/recovery proof includes idle cycles; the separate productive
  scenario proves ten consecutive completed probe jobs. Neither demonstrates
  ten live cross-module scientific or coding-product cycles.
- Hosted schedule activation, Brain-to-live-service routing, and useful live
  cross-module completion remain unverified. Successful historical Actions
  runs or accepted dispatches are not completion evidence.
- Workflow fixes remain local and require authorized publication and review.
  Scheduled behavior on GitHub's default branch cannot change merely because
  a feature-branch patch exists. Integration/default-branch convergence remains
  review- and owner-governed.
- No production deployment, database mutation, provider call, paid service,
  automatic merge, or modification of an active PR occurred.

**The Orchid Continuum is not declared autonomous by this work.**
