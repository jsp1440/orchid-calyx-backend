# Controlled production autonomy rollout (prepared, not applied)

Status: **plan only.** Nothing here has been provisioned. Every step marked
*owner* needs the owner's explicit approval at the time it is taken.

This plan promotes the Brain–Calyx continuous loop that passed hosted
acceptance (17/17 checks, verify run 38443270410,
`deploy/render/evidence/2026-10-13-hosted-loop-confirmatory.json`) to a
long-running worker. It keeps the same safety posture:

- read-only executors only;
- `NO_API_MODE=true`;
- paid execution disabled;
- an isolated database used only for the worker's own state.

## 1. What the production worker does and does not do

It observes the Calyx repository's `main` branch and committed TraitBank batches.
For each genuinely new input it creates work once and runs it with the registered
read-only executors:

- `repository_evidence_reader`
- `isolated_workspace_static_validator`
- `traitbank_batch_validator`

It records durable receipts and learns from the outcomes. Engineering, repair and
module-signal work stay proposals until the owner approves them.

It does **not**:

- call any paid provider or the completion lane;
- write to the production application database;
- ingest or publish scientific data;
- merge, push or deploy anything.

Its only writes go to its own isolated database: cycle receipts, the pulse
ledger, programs and jobs.

## 2. Preconditions (gates, in order)

| Gate | Requirement | Who |
|---|---|---|
| G0 | Brain stack on `main`: #244, #253, #255 (done, `7885869`) | done |
| G1 | Calyx integration PR merged to `main` after owner review, with CI green (done, #1821) | done |
| G2 | Calyx `main` pins Brain `main` (`OC_BRAIN_REF`) in the acceptance CI and the Blueprint (done, in #1821) | done |
| G3 | Start-script confirmation token for a non-acceptance worker (see §6) | Claude PR, then owner merge |
| G4 | Isolated Neon database and read-only verifier role (§4) | owner |
| G5 | Render worker created from the reviewed production Blueprint `deploy/render/autonomy-production.blueprint.yaml` (§3), suspended until G6 | owner |
| G6 | Explicit owner approval to resume and deploy | owner |

## 3. Render worker configuration

Use a separate service, `orchid-calyx-autonomy` (Starter background worker,
Oregon), created from `deploy/render/autonomy-production.blueprint.yaml` (outside the
repository root, the same pattern as `deploy/render/autonomy-acceptance.blueprint.yaml`;
its settings are pinned by `tests/test_render_autonomy_acceptance_config.py`).
The production web service `orchid-calyx-backend` is not touched.

| Variable | Value |
|---|---|
| branch | `main`, **Auto-Deploy: No** |
| `CALYX_ACCEPTANCE_WORK_MODE` | `loop` |
| `CALYX_ACCEPTANCE_SOURCE_BRANCH` | `main` (inputs are real merged changes) |
| `OC_BRAIN_REF` | the Brain `main` commit pinned in CI (40-character SHA, never a branch) |
| `DATABASE_URL` | the isolated autonomy database (`sync: false`, owner-entered) |
| `CALYX_ACCEPTANCE_DATABASE_CONFIRMED` | `autonomy-isolated:autonomy_prod` (§6) |
| `NO_API_MODE` | `true` |
| `OC_GOVERNOR_PAID_EXECUTION_ENABLED` | `false` |
| `PROVIDER_LAUNCH_AUTHORIZED` | `false` |
| `CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE` | `2` |
| `CALYX_PROGRAM_AUTONOMY_POLL_SECONDS` | `30` (idle backoff grows to 900 s) |
| `OC_BRAIN_READ_TOKEN` | the existing fine-grained, Brain-only, Contents: Read-only token |

Cost: one Starter worker, about US$7 a month if left running. The Neon free
plan covers the database at this load.

## 4. Isolated database

- **New database.** Create a database such as `autonomy_prod` in a dedicated
  Neon project, or in the existing `oc-autonomy-acceptance` project. It must not
  be the production application database. The worker creates its 12 `calyx_*`
  tables on first start.
- **Read-only role `oc_verify`.** After the worker's first start, the owner runs
  `GRANT CONNECT ON DATABASE autonomy_prod TO oc_verify;` and
  `GRANT USAGE ON SCHEMA public TO oc_verify;` (in that database). Then
  `GRANT SELECT ON ALL TABLES IN SCHEMA public TO oc_verify;` (the lesson from
  the acceptance run).
- **Verifier secret.** Store a new Actions secret, `OC_AUTONOMY_PROD_VERIFY_DATABASE_URL`,
  holding the `oc_verify` connection string for `autonomy_prod`, separate from the
  acceptance secret.

## 5. Health checks and monitoring

| Signal | Source | Healthy | Action if not |
|---|---|---|---|
| Start-up interlock | first log lines | `acceptance_database: autonomy_prod, confirmed: true`, `api: healthy`, `work_mode: loop` | Suspend; fix config |
| Cycle health | every cycle receipt | `healthy: true`; idle cycles carry a reason (`owner_gate`, `no_eligible_work`, `provider_budget`) | `scheduler_defect`, `configuration_unavailable`, `execution_not_delivered` or `no_executor` three times in a row: the `calyx_health` observer opens a repair proposal; Suspend if repeated |
| Paid lane gated | `coding_lane` in every receipt | `provider_blocked / no-api-mode` | any `queued`: **Suspend immediately** |
| Exactly once | verifier | no duplicate keys, max attempt 1, no leases left held | Suspend; investigate |
| Heartbeat | `status_consistent` | `healthy_waiting` or productive | `stale` while the worker should be running: check Render |

**Verifier cadence.** Run the existing read-only verifier
(`scripts/oc_autonomy_hosted_verify.py --require-loop --database autonomy_prod`)
at these points:

1. after the first hour;
2. after 24 hours;
3. daily during a 7-day soak;
4. weekly afterwards.

All 17 checks must pass. The checks that need a restart or new inputs pass
naturally as real merges arrive. To run it, add the label
`render-autonomy-verify-production` to any pull request:
`render-autonomy-acceptance-verify.yml` then verifies `autonomy_prod` with
`--require-loop`, using only `OC_AUTONOMY_PROD_VERIFY_DATABASE_URL` (it never
falls back to the acceptance credential).

## 6. Required small change before go-live (G3)

`scripts/oc_render_autonomy_acceptance_start.sh` accepts
`CALYX_ACCEPTANCE_DATABASE_CONFIRMED=autonomy-isolated:<db>` for the long-running
worker, alongside the acceptance forms `non-production[:<db>]`:

- the database name is mandatory (`autonomy-isolated` alone is refused);
- it must match `autonomy_[a-z0-9_]+`, so it can never name the production
  application database (`neondb`), `postgres`, or any shared default; anything
  else is refused with `ISOLATED_DATABASE_NAME_REFUSED` before the database is
  contacted;
- a well-formed name is still checked against `current_database()` on the
  connection the app will use, before the API starts
  (`ACCEPTANCE_DATABASE_MISMATCH` / `ACCEPTANCE_DATABASE_UNREACHABLE`).

Tests: `tests/test_render_autonomy_acceptance_config.py` (refusals, unreachable,
mismatch against a real database, and acceptance of a throwaway `autonomy_*`
database). It does not widen any executor or provider permission.

## 7. Rollout steps (after G1–G5)

1. **Owner:** create the worker from the reviewed Blueprint. It stays suspended.
2. **Owner:** enter `DATABASE_URL` for `autonomy_prod` (**Save only**). Resume,
   then **Manual Deploy**.
3. **Claude:** confirm the start-up interlock lines, the first productive
   cycles, and the paid lane gated in the receipts.
4. **Owner:** apply the §4 grants after the first start.
5. **Claude:** run the verifier at 1 hour and 24 hours, and report the receipts.
6. **Owner:** decide whether to continue the 7-day soak.

## 8. Rollback

| Situation | Action | Effect |
|---|---|---|
| Any unexpected behaviour | Render **Suspend** | Stops immediately. The worker settles leases on SIGTERM. No data is lost. |
| Bad deploy | Render **Rollback** to the previous deploy, or set the branch or commit back | The previous code resumes on the same database. |
| Disable the scheduler, keep the service | `CALYX_PROGRAM_AUTONOMY_ENABLED=false`, then Save and redeploy | The worker builds nothing and exits cleanly. |
| Hard stop on any paid path | `NO_API_MODE` stays `true`; `OC_GOVERNOR_EMERGENCY_KILL_SWITCH=true` engages the governor kill switch | The coding lane reports `governor-kill-switch` and cannot run. |
| Remove entirely | Suspend, then delete the service; optionally drop `autonomy_prod` | Nothing else depends on it. |

Nothing in rollback touches the production web service, its database, or any
GitHub branch.

## 9. Out of scope (separate approvals)

- **Paid coding lane:** requires `NO_API_MODE=false`, an allowlisted provider
  and `ANTHROPIC_API_KEY`.
- **Issue handoff** for approved proposals.
- **An approvals interface.**
- **Scientific ingestion and publication.**
