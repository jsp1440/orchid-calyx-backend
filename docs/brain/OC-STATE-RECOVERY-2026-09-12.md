# Orchid Continuum state recovery — 2026-09-12 UTC

Classification: **CONTINUE**. Repository inspection, not a greenfield plan.
Implementation slice: [Calyx #1264](https://github.com/jsp1440/orchid-calyx-backend/issues/1264), read-only completion-health observer attachment.

## Recovered engineering state

| Repository | Inspected default `main` | Current implementation / evidence |
| --- | --- | --- |
| `orchid-calyx-backend` | `0fc7fc5bfbee3fb9cebde99eb45c6ba1b525d674` | Swarm v4 default-branch activation and single-scheduler routing merged in #1321/#1323. Active application/control-plane integration is `oc-autonomous-integration` at `c3cac45773fed2839969b0b0927d19f0ec8335dc`. |
| `orchid-continuum-frontend` | `16af712aa28b48dd54d954f5602cb4b784221b45` | Default branch contains September 5 no-API preparation/parking. Active integration is `00122f000a8060a5aa88b03d2771870ce59b8b2b`, with successful Frontend CI run 34627255011. |
| `Orchid-Continuum-Brain` | `1d7d4d4b7a717b18f373c811aa5b449383fe491a` | Default-branch cost guardrails dated September 6; many later architecture/status proposals remain open. Existing integration ref is `8da12302b18aa41080935749cf649f12fbd717a6`. |
| `orchid-research-station` | `d6382f0ca21c23b3a9d427d8d7dcee2e6e55b23b` | Active React/TypeScript Research Station application using Calyx APIs; analysis workbench/pagination changes merged. Main CI passed (31995875924). README still explicitly identifies prototype data and production-readiness limits. |
| `orchid-continuum-control-panel` | `9a067f639f09f583c667d1b861086e9975fbfc4e` | Mission Control telemetry proxy; not the coding scheduler. Main CI passed (31987849993). |
| `Orchid_Continiuum_Backend` | `8ea053b292627ec35cc5ef1aaa2f99b9c89aff58` | Separate legacy harvester/backend; dispatch/persistence repair merged July 22. Preserve it; it is not the default Calyx implementation target. |
| `orchid-continuum-backend` / `orchid-continuum-core` | `4a44b02efb2d60d52a548dc407530b3a6f5cbd83` / `a4207d2419a122642674e1407fa991234868e144` | Historical/other application repositories, not substitutes for the canonical Calyx backend. No Actions runs returned by the inspected repository endpoints. |

The GitHub connector supplied private Brain/Research Station records. Direct unauthenticated cloning worked for public Calyx/frontend only. No production database or deployment console was accessed. GitHub Projects boards were not exposed by the available connector; issues, PRs and repository queue contracts were inspected instead.

### Already completed: do not rebuild

- BUILD-076B commit `3307caae2cf5ce596731c496cd922509e05c8477` is an ancestor of Calyx `main`; merge #67 exists. Extraction evidence and candidate records are already separate.
- Integration contains Scientific Memory project-scoped capture/recall/append-only decisions; source evidence, candidates and inference remain separate. It does not authorize canonical KG publication.
- Recent integration merges include #1276 (governed KG materialization/read-through), #1296 (canonical literature binding), #1346/#1348/#1350–#1356 (reserve refill, audit/source/Brain-gap/DeepOrchestrate/task bridges), #1342/#1347/#1349/#1358/#1359 (executor proof, result handling, bounded draft targeting and canary work), #1188 (research recovery), and #1180 (scientific observability).
- #1357 already added the completion-health snapshot producer/core contract composition. This session extends that code; it does not introduce another health checker or scheduler.

### Integration and documentation discrepancies

- Calyx promotion PR [#1199](https://github.com/jsp1440/orchid-calyx-backend/pull/1199) is open/conflicted: 451 changed files and 673 commits reported at inspection. Git shows 673 integration-only commits and four main-only commits. A read-only `git merge-tree` identifies conflicts in completion-lane, continuous-completion, Gemini canary, Swarm controller and three orchestration test files. No merge was performed.
- Frontend promotion PR [#493](https://github.com/jsp1440/orchid-continuum-frontend/pull/493) is also open/conflicted: 311 files and 448 commits reported. Green branch CI does not make either promotion approved or production-deployed.
- `docs/ORCHID-SWARM-CONTROLLER.md` still says default-branch activation is future work, although #1321/#1323 activated the relay. `docs/SOFTWARE-FACTORY-V1.md` lists queue/checker wiring as future slices even though factory/event/checker modules now exist on integration. Module presence alone still does not prove the full runtime loop.
- Brain's repository registry calls `orchid-research-station` backend/services and the separate `orchid-research-station-frontend` active UI. Actual READMEs/package trees disagree: the former is the active React/TypeScript application; the latter explicitly preserves the historical standalone export.
- Brain OPS-0012 is an August 16 snapshot of a different one-shot experiment. Its historical credential/CI findings must not be generalized to the September Swarm implementation.
- There are more than 1,600 Calyx remote refs. Many are retained merged/historical lineages (including BUILD-076B and duplicate Matrix branches); age or retention alone is not evidence that every branch is abandoned. No branches were deleted or historical PRs revived.
- Frontend researcher-profile PRs #516/#585/#623 and Research Station #27 overlap; Brain #134 already calls for convergence. They were not touched.
- Backend #1362 is active producer work for #1360; #1361 explicitly depends on it. Do not bypass that dependency or implement its consumer against an unvalidated producer. #1363's initial Ruff failure was repaired: current head `1a9ad49faf3d1211d7b670e5b18b97f3283ed3fb` has successful checks. Historical red attempts are not current-head failures.

## How much of the autonomy loop is demonstrated?

| Segment | Evidence tier / remaining boundary |
| --- | --- |
| Literature intake -> extraction -> evidence/candidates | Implemented; focused extraction tests rerun successfully. Scientific review remains mandatory. |
| Evidence -> Scientific Memory / KG -> reasoning | Existing project-scoped memory and governed KG contracts pass focused tests. No production migration or publication was run. |
| Question -> Research Station -> immutable review artifact -> feedback/replay | #1188 supplies the real runner/store bindings and executable tests. Local proof uses controlled domain readers and local/in-memory stores; it is not a live production mission. |
| Brain gaps / audit / existing tasks -> reserve -> dependency/resource planning | Existing bridges and Swarm planner pass local tests. #1361's innovation admission still awaits #1360. |
| Worker -> validation -> integration | GitHub PR/check/merge history demonstrates non-main integration activity. Full backend integration receipt run 34668183522 is successful but covers compilation and a focused Matrix slice, not the entire backend suite. |
| Integration -> deployment -> observed scientific benefit -> new memory | Not demonstrated end to end. Conflicted promotion PRs and owner-controlled activation remain. Calyx #1187 explicitly requires a deployed readiness receipt and bounded real acceptance mission. |

Swarm integration run [34670742864](https://github.com/jsp1440/orchid-calyx-backend/actions/runs/34670742864) completed successfully, but its plan selected zero workers: #1361 was dependency-blocked by active #1360. Its log recorded providers allowed (`NO_API_MODE=false`); this session did not change that setting or invoke a provider. The successful run is evidence of scheduler execution, not proof of scientific or engineering completion.

## This implementation slice

The existing observer watched only the retired completion workflow and printed its conclusion. It never called the canonical health checker. Completing this attachment is the highest-value safe unattended slice available without overlapping active literature work or crossing production approval gates.

Changes on `oc/health-observer-1264`:

- Extend `scripts/oc_control_plane_health.py` with a bounded GET-only GitHub adapter and `--check`/`--summary` CLI. Reuse `scripts/oc_health_contract.py` and the existing no-API policy.
- Read queue labels, current PR heads, versioned lease claims/settlements, material fingerprints and controller execution evidence. Recheck inventories and integration head; refuse incomplete, ambiguous or changing observations.
- Read at most 80 API responses, five pages per inventory/recent comment window. Missing older lease history is incomplete unless a recognized later settlement establishes a boundary. Never replay old settled claims as active work.
- Use actual 16-character work-packet fingerprints. A running label is not a fabricated lease; a successful run with no executed job evidence remains UNKNOWN.
- Attach the existing observer to integration Swarm/completion runs; use the observer's trusted code revision, read-only token permissions and no persisted checkout credentials. Preserve the JSON artifact even on contract failure.
- `healthy` means observed contract consistency, not production readiness. Provider health, integration approval and unmeasured deployment state remain UNKNOWN. No mutation/repair/dispatch/publication authority is granted by this receipt.

### Verification

- 66 focused tests passed: observer adapter/CLI/workflow plus canonical health and exception contracts.
- 131 recovered-path tests passed: BUILD-076B, Scientific Memory, KG, Atlas, research execution, Swarm dependencies/locks, factory and reserve bridges.
- Changed-file Ruff passed. `python -m compileall -q app runtime harvesters scripts` passed. `git diff --check` passed. Observer run shell parsed with `bash -n`; stdlib-only CLI import/run passed with `python -S`.
- Replay of connector-fetched repository receipts found one queued, one running, ten validating, seven repair-backoff and two blocked issues. It reports #1360 without a durable lease and ten validating issues without an unambiguous current open-PR head. These are observation gaps, not authorization to relabel or redispatch them. After recognizing actual settlement formats and bounded recent history, collection completed without transport/truncation errors.
- The live-evidence exercise is a replay of captured GitHub API responses, not an activated hosted observer. Hosted validation is recorded on the implementation PR. No full-repository test count or production success is claimed.

### Remaining checkpoint / next recovery

Review the implementation PR and exact-head CI before activating the workflow. This is a maker-produced change; this session is not independent acceptance for automatic integration. Promotion to `main`, workflow activation, deployments, paid execution and scientific/data authority remain owner-governed.

#1264 remains open: this delivers its backend read-only observation slice. Wiring a mutating healer or making it consume the receipt is separate work; no healer was activated here. First recover actual current queue/PR state again, then reconcile the missing lease/validation evidence without redispatching unchanged completed work. Keep #1361 dependency-blocked until #1360 is validated. Preserve the conflicted promotion batches for a separately reviewed integration task.


## Follow-up: verified Swarm handoff recovery (2026-09-12)

This section supersedes the earlier “next recovery” instruction and any broad
claim that green workflows prove the complete autonomous loop. Continue the
existing held draft [#1364](https://github.com/jsp1440/orchid-calyx-backend/pull/1364)
on `oc/health-observer-1264`; no additional branch, repository, service or database
was created. The original observer commit remains `ae9b814e13dd7c60dcede2f90851f5e16148e05c`.

### Dependency root cause — VERIFIED, legitimate / unresolved

The executed planner in [run 34672666097](https://github.com/jsp1440/orchid-calyx-backend/actions/runs/34672666097)
reported one queued candidate, one active worker, seven available slots, and zero
launches. #1361 declares exactly `OC-SWARM-DEPENDS-ON: #1360`; the parser resolves
1360, with no missing dependency or cycle. Its producer remains open/running,
without `oc-done`. The dependency implementation accepts closed or `oc-done`
issues, so suppression is correct. No closure, relabeling or fabricated completion
was used to clear this gate.

#1360 explicitly records a local maker claim. It has zero issue comments and its
actual deliverable is draft [#1362](https://github.com/jsp1440/orchid-calyx-backend/pull/1362),
head `10652adbf81d5f19b6e609b53eed9d511d3b4ea2`, with no submitted independent review.
Most checks passed, but [PostgreSQL validation 34665841358](https://github.com/jsp1440/orchid-calyx-backend/actions/runs/34665841358)
failed in job 103477428597: `scripts/build_077_postgres_validation.py:628` invoked
the full backend pytest subprocess and discarded its failing captured output.
The log shows a configured remote database target and migration checks. It was
not retried because production mutation is outside this session's authority.
The underlying failing tests are UNKNOWN, not assumed baseline failures.
The PR's “hosted validation pending” text is STALE: execution occurred, with this
failure outstanding. The absent Swarm lease is a separate manual-maker tracking
inconsistency; it does not make the producer complete or authorize duplicate work.

### Smallest repaired boundary — PARTIAL until activated

The first unreliable boundary is planned selection to confirmed lease ownership:
the old controller retained `oc-queued` while adding `oc-running`, and dispatched
the original matrix even when its claim loop skipped a candidate. Worker admission
then checked only a running label, allowing an unrelated/stale dispatch to use it.

The existing shell claim loop is extracted to `scripts/oc_swarm_claim.py`, using
the same queue/dependency policy, work packet and health contract. It rechecks the
issue and dependencies, removes queued while claiming running, confirms the durable
comment, and emits only confirmed workers. Receipts include run/attempt/issue
identity and the existing material fingerprint. Both worker paths consume the exact
comment ID and verify ownership before execution; a rejected provider-free handoff
does not run settlement against another actor's labels. Legacy direct/manual lane
calls retain their previous label-only behavior; they are not certified by this change.

The observer reads fingerprints at claim time and rejects claim/worker disagreement.
A retained handoff artifact distinguishes planned, confirmed, skipped and failed
claims. Partial GitHub writes remain explicit anomalies with no worker dispatch;
there is no blind retry or label rollback that could overwrite another actor.
GitHub label/comment writes are not atomic. Cross-actor resource races, workflow
cancellation recovery and lost-lease reconciliation remain unproven; this patch
does not claim a transactional lock service or heal old queue records.

### Actual acceptance evidence

[Machine-readable observation](evidence/OC-SWARM-2026-09-12.json) records 37 fresh,
sequential connector GETs through the actual observer adapter, followed by the
actual Swarm planner and its zero-worker handoff. It is a local read-only execution,
not captured-response replay or hosted observer activation. No worker receipt was
invented. Observation completed without collection errors and remained UNHEALTHY:
#1360 has no durable running lease; ten validating issues lack an unambiguous current
open-PR head. The observer's local fail-closed provider default is explicitly
identified and is not claimed to be the live repository variable.

| Stage | Status and exact evidence |
| --- | --- |
| Queue observation and dependency rejection | VERIFIED live now: #1361 -> #1360, zero selected; executed scheduler job 103496873545 and fresh read-only observation agree. |
| Correct exclusive claim and worker handoff | PARTIAL: regression-tested repair, not activated; zero-worker live path only. |
| Actual worker execution / PR delivery | VERIFIED historical canary #1355, run 34661972275, worker job 103466204903, packet `d6d268b43b8817c0`, delivered #1359 at `a6b12e0f3d5ff9411fa9b0c686bc678b1a88c681`. No new worker ran here. |
| Changed-file validation | VERIFIED historical: #1359 run 34662028519, job 103466334113 executed Ruff and two tests successfully. Full product validation is not implied. |
| Independent governed integration decision | BLOCKED/unproven: #1359 was merged to integration, but has no submitted independent review and no recovered factory PASS receipt. A merge record alone is insufficient. |
| Durable evidence | VERIFIED issue claim/start/settlement comments for #1355, PR/check/run records, and this redacted recovery receipt. New positive claim artifacts await activation. |
| Useful unattended task across the complete loop | BLOCKED: no new positive live worker acceptance. Current model lane can bill a provider; deterministic reconciliation only applies a declared disposition and is routed by the global NO-API setting. It is not evidence-assessed useful execution. |
| Production deployment / scientific feedback | BLOCKED at owner-governed boundaries; not exercised. |

Validation: 155 focused tests passed across claim, planner, dependencies, locks,
write-set, provider-free worker, health observer, invariants, exception policy,
repair-backoff and provider/workflow gating. Changed-file Ruff, Python compilation
of app/runtime/harvesters/scripts, standard-library-only claim CLI import,
workflow YAML parsing, 30 shell blocks via `bash -n`, and `git diff --check` passed.
The pre-existing workflow contract test was updated to follow the extracted claim
code; behavioral coverage now includes each parked state, duplicate claims,
reopened dependencies, changed issue material, unconfirmed receipts and wrong
worker run/attempt/comment/fingerprint. Hosted results belong in the PR and Brain
post-commit receipt; no full repository suite or live PostgreSQL PASS is claimed.

### Next highest-priority autonomy blocker

First obtain independent exact-head review and owner approval for activating the
held handoff/observer changes. Then prove one useful bounded task with an execution
route that cannot accidentally enter a paid lane, stopping at an explicit governed
integration decision and retaining its receipts. The existing provider-free route
must assess evidence rather than trust a predeclared `done` marker, and its routing
must remain provider-free regardless of global provider availability. Do not mark
a task done just to make a canary green. The separate #1360 producer validation and
checker gate must be resolved before #1361 can enter engineering execution.
