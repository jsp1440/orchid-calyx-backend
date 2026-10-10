# R1 canonical Brain/Calyx integration candidate

## Source and scope

This patch is based on the complete approved Calyx integration checkout,
`oc-autonomous-integration` at
`4a2b48dd05d7f578eee20aff248c923a585eceb8`. It is not a continuation of an
isolated snapshot history. The new local branch is
`replit/r1-autonomy-integration-20261008`.

The preserved implementations remain separate provenance refs:

| Candidate | Original commit | Archive SHA-256 |
| --- | --- | --- |
| Real-worker fencing | `8e6f7eb9db6a02114faf70d66e197bb8286ceb0f` | `4605357d97b0a14c09d3a13871c0a1073a61180296b5f86c34075cffe656a5f5` |
| Local ten-cycle recovery | `84392ba954efa509d034b65cee1b604890cdbc32` | `55b9288b773aacd639c7748d7ae1e857364cfba2a75f6313e20abda1b47f7867` |

Their original archives, patches, bundles, hashes and receipts are preserved.
The previous 22-test, 76-test and ten-cycle evidence was not rerun. The old
snapshot workflow-routing changes were not copied wholesale into this checkout.
Only compatible worker fencing and the durable queue handoff were integrated.
No new scheduler, queue implementation, executor fallback or scientific module
was introduced.

## Actual integrated path

The mounted canonical Brain router now exposes authenticated
`POST /brain/canonical/builds/submit`. Its schema is
`canonical-brain-program-handoff.v1`, with:

- Governed `BuildAdmissionRequest` records, explicit registered-role metadata,
  explicit dependency pairs, and inputs for exactly the admitted build IDs.
- Ownership from the existing authenticated session subject or API-key actor,
  never a request-body owner. The existing shared backend API-key identity is
  a service ownership namespace, not a per-human identity.
- Server-captured admission provenance. Input fields cannot replace the reserved
  provenance record. Provenance is a declaration, not scientific verification.
- Admission, dependency-cycle, duplicate-ID, role and side-effect checks before
  durable writes. Unknown roles, the internal `autonomy_probe` test executor,
  mutation and external-effect executors fail closed.
- Existing `PersistentProgramRepository`, registered executor registry, SQL queue,
  fenced worker leases, execution bridge, completion and dependency release.
  Replay does not resume cancelled, paused or completed programs.

PostgreSQL owner-scoped advisory locking serializes admission. Identical batches
converge on the existing program; conflicting manifests and partially overlapping
canonical batches reject rather than enqueueing the same owner/build twice.
Build IDs can be reused in a different authenticated owner's namespace.

The focused HTTP-to-worker test invokes this actual router, native PostgreSQL,
and the actual `repository_evidence_reader` bound to its configured private Git
worktree. Two dependency-linked source-verification jobs execute and complete.
The next dependency is released by the existing program mechanism. A different
owner cannot claim them. Two concurrent authenticated submissions converge.
This is operational source verification, not scientific completion.

The existing hosted Brain pulse still materializes GitHub issue packets. It was
not silently redirected into SQL, and no hosted or remote Brain submission was
made. Adoption of this typed SQL intake by the upstream Brain caller, with
approved role metadata and authenticated ownership, remains a rollout gate.

## Real GitHub workers

Both existing completion lanes now:

1. Require a durable claim; labels or packet identity alone do not admit a worker.
2. Use history-aware `verified_issue` at admission and immediately before work.
3. Use `settle_worker` for claimed-task result comments and queue labels,
   including terminal failures and governor dispositions.
4. Reject expired, future-dated, superseded, incorrectly owned or malformed
   authority without overwriting another claimant's queue state.

The history-aware guard reads later comment pages and uses timestamp/comment-ID
ordering. Recovery now also reads beyond its previous ten-page cutoff. An
incomplete or invalid comment response, exhausted 100-page history bound, or
malformed authenticated claim is a refusal, not permission to recover an older
claim. Normal scheduler, queue, dependency and module routing remain intact.

### Ninety-minute GitHub ownership policy

The lease still expires 90 minutes after the authenticated receipt timestamp.
There is no GitHub renewal protocol, progress-comment renewal, label bypass, or
expiry extension. Queue wait and setup consume that lifetime.

Both worker jobs now have an explicit 70-minute job timeout. Admission and each
module/provider entry require at least 75 minutes remaining. Thus queued/setup
claims older than 15 minutes cannot start another execution segment; fresh
bounded executions reserve time for settlement. Settlement itself requires a
valid current unexpired claim, not another fresh 75-minute execution window.

A legitimate current-claim job inside these bounds remains admissible.
Receiptless legacy jobs, old owners and expired claims fail closed. They require
owner-reviewed readmission after the actual old execution has stopped; relabeling
alone is not a migration. Running/queued/unknown runs are not declared stopped
solely because a receipt is old. Terminated-run recovery remains canonical.

Jobs requiring more than this supported window must be split or obtain a separately
designed ownership/renewal protocol. These changes do not support unbounded
long-running GitHub jobs.

### Native SQL ownership policy

The native cycle now calls its existing atomic, token-fenced heartbeat after
claim/role validation and before execution. It reserves the configured execution
timeout plus 30 seconds, or the larger configured lease. An expired or superseded
token cannot renew. Budgets exceeding the existing 3,600-second lease ceiling
reject before claiming; consequently the maximum supported configured execution
timeout is 3,570 seconds. Default 300-second execution receives a 330-second
execution/settlement lease rather than an equal-length 300-second lease.

This is bounded pre-execution renewal, not a periodic heartbeat daemon. A module
that ignores its deadline or leaves asynchronous external work running is outside
the supported bounded contract. The existing fenced completion path still denies
stale settlement. A proper periodic-renewal/cancellation design is necessary
before admitting such work; increasing TTL or trusting progress comments is not
proof of termination.

### Remaining race — no exactly-once external effects

GitHub claim reads, receipt writes, result reads and label writes are separate
operations. Ownership can change after the final check, and two processes with
the identical claim identity can both pass an earlier execution check. A cancelled
runner cannot retract an already sent external request. Native SQL token fencing
protects lease updates and completion, not arbitrary external effects.

Neither these tests nor this patch establish exactly-once execution or
exactly-once external effects. External-effect idempotency, atomic authority and
reliable cancellation require a separate design and approval. Previously running
incompatible workers must be quiesced before activation.

## Focused test evidence

`scripts/oc_r1_integration_test.py` starts disposable native PostgreSQL on an
owned loopback port, passes an allowlisted environment with no inherited
credentials, disables paid execution and provider launch, and installs the
existing outbound socket guard. Only the two changed integration test files can
be selected. GitHub writes are simulated. Git worktrees are private test fixtures.
No production database or hosted workflow is accessed.

The delivery contains the raw logs and JUnit receipts from every focused attempt,
including corrected test-fixture assumptions. The latest passing receipt for each
case is summarized separately; this is incremental targeted verification, not a
claim that the old broad suites were rerun against this candidate.

Coverage includes authenticated intake, client ownership/schema rejection,
unsupported/test roles, failed governance, dependency rejection, concurrent
producers, partial batch overlap, real execution/dependency release, fenced
native renewal, unrenewable budgets, claim expiry/budget boundaries, superseding
and malformed claims on later pages, incomplete recovery history and real
workflow guard/timeout/settlement wiring.

Python E/F checks, patch whitespace checks, YAML parsing and Bash syntax checks
also passed. Workflow bodies were not dispatched and paid executors were not run.

## Narrow hosted zero-launch diagnosis

Read-only evidence:
<https://github.com/jsp1440/orchid-calyx-backend/actions/runs/37879106379>,
scheduled at `2026-10-09T03:24:10Z`.

- Workflow event SHA: `f32d508677ffe3765c9e8c380d7d2619023ee6eb`.
- Actual canonical code checkout: `4a2b48dd05d7f578eee20aff248c923a585eceb8`.
- Planning succeeded. Worker jobs skipped because launch count was zero.
- Brain pulse reported 18 candidates. Brain materialization reported zero
  creations/requeues; repository discovery reported zero candidates. These
  counters alone do not identify every materialization skip reason.
- The planner reported one queued open issue, zero eligible/launchable jobs, zero
  active workers, and unfinished open work. This was not healthy completed idle.
- Issue **#1742** was unstaffed: its declared deterministic outputs were not an
  actual coding executor. It required `open-ended-code-authoring`, reported
  `coding_executor_available=false`, and refused the lane with
  `no-authorised-coding-executor`.
- Homeostasis explicitly reported `capability_gap` / `lane_refused`. Other work
  remained held, owner-gated or deliberately parked.

Therefore the measured immediate zero-launch cause is **no authorized executable
eligible work**, not an absent scheduler trigger. Producer stages ran; the new SQL
intake was not the historical hosted producer, so lack of this new intake is not
proven to have caused that receipt. No version incompatibility exception was
observed, but deployed Brain/Calyx compatibility has not been established.

The older default-branch workflow template and canonical integration checkout
are different sources. In particular, integration-only intake/evidence stages
are not established by a main-branch event SHA. Default-branch convergence
requires separate approval. Empty confirmed-claim health is not autonomy success.
The selected log diagnostics are preserved in `Orchid_R1_Hosted_Diagnosis.json`.

## Exact remaining activation requirements

1. **Automation-safe publication approval:** establish a branch/draft-PR path
   that cannot trigger unintended hosted automation, paid workers or deployment,
   and explicitly authorize it. Workflow-file write permission must be confirmed.
   No remote branch or draft PR was created in this work.
2. **Version/contract adoption:** approve exact Brain and Calyx versions, wire the
   upstream caller to the typed authenticated intake where appropriate, and confirm
   role registration, provenance, dependency and service ownership contracts.
   Do not substitute a test or source-reader executor for scientific/coding work.
3. **Eligible executor decision:** provide real supported work or approve an
   appropriate bounded coding executor for the measured #1742 gate. No spend,
   owner, scientific or provider gate was removed here.
4. **Runtime readiness:** confirm the existing PostgreSQL program tables and
   trusted worker repository/branch scope; choose the matching authenticated
   `CALYX_PROGRAM_AUTONOMY_OWNER` and deliberately approve
   `CALYX_PROGRAM_AUTONOMY_ENABLED`. No runtime settings were changed.
5. **Lease-safe rollout:** quiesce incompatible live workers, explicitly readmit
   receiptless/expired legacy work only after its old execution stops, and restrict
   jobs to supported budgets or approve a longer-job renewal/cancellation design.
6. **Separately approved hosted proof/default convergence:** only then authorize
   exact-head hosted dispatch, controller receipts, approved default-branch
   convergence and scheduled activation. Local receipts do not satisfy that gate.

Active PRs #1792 and #226 were not altered. There was no merge, deployment,
production mutation, paid-provider call, hosted dispatch, whole-workspace staging,
or retry of the broken workspace checkpoint.
