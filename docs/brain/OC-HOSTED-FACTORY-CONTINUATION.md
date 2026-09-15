# Hosted factory continuation

Status: PARTIAL / BLOCKED — hosted infrastructure merged in #1370 at
05ca7d3e19471e43d947ca80361d92203fc96241; useful live proof #1371 stopped
before provider initialization at the unchanged monthly budget ceiling.

Baseline: integration `889196f029f397aa17f8142e11f0753611033f3a`, successful
maker #1365 / PR #1369, canonical Brain recovery `c1949ffc4fb699cc91162da1f9c6b2a15ba80ffe`.
The prior checker, factory API use and final settlement were coordinator actions.
They are VERIFIED HISTORICAL, not evidence of unattended completion.

## Existing architecture, connected

The completion lane dispatches the existing convergence supervisor after creating
its PR and dispatching validation. Dispatch inputs bind issue, PR, full maker SHA,
Swarm run/attempt and confirmed claim comment. The supervisor executes its immutable
trusted integration revision and polls actual worker/validation completion. It
never checks out or imports candidate code. This hosted dependency dispatch is
normal operation; workflow_dispatch is also the recovery entry point. The old
PR-body-marker-only merge implementation is removed on integration. Main remains
unchanged; its old scheduled definition is not claimed repaired or promoted.

The adapter consumes checker_dispatch, factory_bridge, dependency/write-set and
health contracts. An independent no-tools checker session receives the complete
bounded patch and task, with strict JSON verdict/risk fields. Required hosted
validation job/steps must actually have run on the exact head; all observed checks
must be green. Missing, truncated, stale, contradictory or ambiguous evidence
fails closed. Shared checker evidence decoding now rejects non-boolean check flags.

An owner-authored, unedited, expiring OC-HOSTED-FACTORY-AUTHORIZATION-V1 comment
enrolls one bounded issue. Its JSON binds repository, issue, full title/body digest,
exact allowed paths, integration target, low/moderate risk and checker_calls=1.
It grants no protected-path, main, production, scientific, credential or destructive
authority. PR text cannot grant authority. The separate checker can only narrow
this scope. A single attempt and conservative $0.08 ledger reservation are persisted
before provider credentials initialize. Existing NO-API, kill switch, provider
allowlist, budget and global paid concurrency controls all still apply. There is
one capped request, at most 48,000 review bytes and 1,800 output tokens; no fallback
or automatic paid retry. A consumed uncertain attempt stays consumed.

A separate privileged job rereads all mutable authority and the exact checker
comments produced by this run, invokes the existing factory gate, and uses the
GitHub merge API's expected-head SHA fence. The actual merged PR and both merge
parents must match before a verified merge receipt is persisted and read back.
Only then can the issue close as completed/oc-done. A partial failure never invents
success, requeues paid work or removes owner/backoff boundaries.

## Durable observation and continuation

The existing full health observer runs after factory completion (including failed
completion), retaining all violations. Its evidence and exact checker/factory/
settlement records are captured create-only under existing docs/brain/evidence/,
with blob-content readback and a linked issue receipt. These are engineering Brain
mirror records, not canonical scientific evidence. Hosted writes to the separate
Orchid-Continuum-Brain repository remain UNPROVEN: no cross-repository credential
was introduced. Central Brain can link these immutable records through the existing
engineering recovery process.

Paid refill now follows factory settlement and a healthy observer, under existing
OC_GOVERNOR_AUTO_REFILL authorization and the same bounded wave ceiling; default
automatic refill is not enabled. Provider-free refill keeps its existing path.
Current known 11 health violations remain visible and block paid continuation.
One task may be fully completed while global health remains unhealthy.

## Verification and remaining limits

Tests exercise successful execution of the adapter against a fault-injecting
GitHub transport and fail-closed authorization, claim/fingerprint/dependency,
validation/runner, strict checker output, owner boundaries, exact merge, receipt
readback, replay and observation failures. These tests are not live evidence.
Executor/governor/governance suites and hosted CI are required before activation.

An old v4 workflow test expected a deleted shell receipt expression. It fails on
the unchanged 889196f0 baseline; the updated contract checks the actual confirmed
claim adapter and its matrix output. Executable claim tests remain unchanged.

No claim of concurrent multiworker reliability follows from sequential canaries:
GitHub concurrency can replace pending runs, existing stale queue evidence remains,
and main/default-branch promotion and canonical Brain synchronization are separate
boundaries. #1361 still legitimately depends on unvalidated producer #1360/#1362.

### Required-status authority recovered before activation

Fresh GitHub metadata on 2026-09-12 reports integration protected=false, enforcement
'off', contexts/checks empty, and no rulesets. All seven Actions checks on initial
implementation 39a6273a passed, but optional recurseml/analysis returned error. The
same optional error exists on historical accepted #1369 and #1368. It is retained
as failure evidence, never called green. The initial draft incorrectly required
all optional combined statuses to succeed; the corrected adapter derives required
status authority from GitHub policy, enforces all required contexts/app bindings,
retains complete advisory status evidence, and fails closed on active/unknown
rulesets. No existing required gate or check was removed or waived.


### Actual bounded launch — BLOCKED at paid admission

Initial launch #1371 produced Swarm run 34678424277: claim5644219216,
packet289d2911fe5e5789, worker103512386892, admission5644220292,
denial5644220478. Dependencies were eligible and #1361 remained blocked by #1360.
The governor read monthly reservations9.75 plus proposed0.50 against ceiling10.00;
daily2.50/10.00 and per-run0.50/2.00 were within limits. No credentials initialized,
model call, PR, checker call, factory decision or oc-done occurred. Scheduler green
is not useful execution evidence.

The existing denial path returned the task to queued. A second hosted admission
(run34678449115, claim5644222071, start5644223160, denial5644223368) hit the same
ceiling before provider execution. The coordinator then parked #1371 in oc-blocked
(comment5644224895). This was manual failure containment after a failed proof,
not unattended success. No second independent task was launched.

Ledger audit:18 entries,18 distinct run IDs, total9.75 this month; all actual costs
unknown. There is no evidenced duplicate or safe refund. This attempt made zero
provider requests and added zero reservations. Limits and reservations were not
lowered, raised, reset, refunded or bypassed.

The denial lifecycle follow-up parks only an exactly verified bot claim, verifies
blocked labels and a durable release receipt, and never restores paid eligibility.
The observer recognizes historical denials only for the matching repository/run/
fingerprint and modern releases for the exact claim comment/lease/fingerprint.
Unmatched, forged, malformed or ambiguous release evidence remains an error.

Fresh pre-fix observer:39 live GETs, complete, unhealthy with14 violations: the
11 earlier violations plus two orphan claim interpretations and duplicate packet
fingerprint from the denied retries. Replay with the corrected denial parser
retains all records and all11 original violations; it recognizes the two actual
denials as scoped releases. Replay is not new hosted proof. Full task execution,
hosted checker/factory/settlement/Brain capture and two-run repeatability remain
UNPROVEN. Legitimate monthly budget headroom is the next external blocker.
