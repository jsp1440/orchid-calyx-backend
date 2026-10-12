# Hosted autonomy acceptance on Render + Neon (prepared, not applied)

Nothing in this directory provisions anything by itself. Render only syncs a
root `render.yaml`. This Blueprint is used only if the owner creates it from its
path. It never touches the production web service `orchid-calyx-backend` or the
production database.

## What runs

One Render **background worker** (`orchid-calyx-autonomy-acceptance`) runs
`scripts/oc_render_autonomy_acceptance_start.sh`. The script does the following:

1. Refuses to start (one `configuration_unavailable` line, exit 0) unless
   `CALYX_ACCEPTANCE_DATABASE_CONFIRMED=non-production` and every required
   variable is set.
2. Clones this public repository at `CALYX_ACCEPTANCE_SOURCE_BRANCH` into a
   disposable, read-only `autonomy/hosted-acceptance` workspace with the
   isolation marker.
3. Fetches the Brain repository at the pinned `OC_BRAIN_REF` with
   `OC_BRAIN_READ_TOKEN`. The token travels as an HTTP header and never
   appears in a URL, the remote config or a log.
4. Builds the work manifest with Brain's own packet builders:
   - one TraitBank batch-validation program per committed `data/traitbank/*.json`;
   - up to 16 repository-verification programs, chained by `depends_on`.
5. Starts the real Calyx API on `127.0.0.1:8000`. The API is not reachable
   from outside the container.
6. Starts `python -m runtime.program_autonomy_brain_worker`. Each cycle runs:
   Brain pulse (select, check dependencies, submit) → Calyx admission →
   lease → registered read-only executor → verified receipt → durable cycle
   receipt → next cycle.

On SIGTERM (Render stop or deploy) the worker finishes its cycle, settles its
leases, exits 0, and then the API stops.

No provider, paid API, TraitBank ingestion, publication or production write
is reachable. Every executor in the registry is read-only, and `NO_API_MODE`
is on.

## Cost (smallest configuration)

| Item | Choice | Cost |
| --- | --- | --- |
| Render worker | `starter` instance (the smallest background-worker type; workers have no free tier) | US$7/month list, **prorated per second**. One hour ≈ US$0.01; a full day ≈ US$0.23 |
| Neon database | New free project (option A) or a new database in the existing project (option B) | US$0 within free-plan limits. The acceptance writes a few hundred rows. |
| GitHub | Fine-grained token | US$0 |

Suspend the worker when the run finishes. A suspended Render service is not
billed for compute.

## Owner steps

### 1. Neon: an acceptance-only database (never production)

Option A, full isolation (recommended):
1. In the Neon console choose **New project**, name it `oc-autonomy-acceptance`, Free plan.
2. Copy its pooled connection string. Paste it only into Render's
   `DATABASE_URL` field (step 3). It is never committed or pasted into chat.

Option B, no new project:
1. In the existing project create a database `oc_autonomy_acceptance` and a new
   role that owns only that database.
2. Do **not** use a branch of the production branch. A Neon branch is a
   copy-on-write copy of production data.

Either way, the Calyx code creates the tables on first use
(`ensure_orchestrator_schema`). No migration is run against production.

### 2. GitHub: `OC_BRAIN_READ_TOKEN` (read-only, Brain only)

No existing credential fits:
- `GITHUB_TOKEN` cannot read another private repository.
- `CALYX_GITHUB_CODING_AGENT_TOKEN` is write-capable and confined to one gated
  canary step.

Create a fine-grained personal access token:
1. GitHub → Settings → Developer settings → Personal access tokens →
   **Fine-grained tokens** → Generate new token.
2. Resource owner `jsp1440`, expiration 30–90 days.
3. Repository access: **Only select repositories** →
   `jsp1440/Orchid-Continuum-Brain`.
4. Repository permissions: **Contents: Read-only**. Metadata: Read-only is
   added automatically. Grant nothing else.
5. Store the value in two places only, typing it into each settings page directly:
   - Calyx repository → Settings → Secrets and variables → Actions → New
     repository secret `OC_BRAIN_READ_TOKEN` (used by the
     `brain-calyx-autonomy-acceptance` workflow);
   - the Render worker's `OC_BRAIN_READ_TOKEN` field (step 3).

**Current state (2026-10-12):** the Calyx Actions secret `OC_BRAIN_READ_TOKEN` was empty on
2026-10-11 (the Brain step in `oc-completion-receipt-contract` was skipped). It is now set, but the
token is refused for the Brain repository. The `acceptance` checkout of
`jsp1440/Orchid-Continuum-Brain` returns `403 Write access to repository not granted`, which GitHub
also returns for read requests from a token that is not granted access to that repository. Fix the
token rather than the workflow:
- edit the fine-grained token and add `Orchid-Continuum-Brain` under **Only select repositories**,
  with Contents: Read-only;
- confirm its resource owner is `jsp1440` and that it has not expired;
- if it was created as a different kind of token, replace the secret value with one made as above.

Equivalent alternative: a GitHub App installed only on the Brain repository
with Contents: Read-only. Its installation token is short-lived, so it needs a
small token-minting step before the fetch. Use the PAT for this acceptance.

### 3. Render: create the Blueprint from its path

1. Render dashboard → **New** → **Blueprint** → repository
   `jsp1440/orchid-calyx-backend`.
2. Branch `claude/sharp-pasteur-e6c4r1-traitbank`, **Blueprint path**
   `deploy/render/autonomy-acceptance.blueprint.yaml`.
3. Fill the two `sync: false` values: `DATABASE_URL` (step 1) and
   `OC_BRAIN_READ_TOKEN` (step 2). `CALYX_API_KEY` is generated for this
   service only.
4. Check that the plan shown is `starter` and that no other service is listed.
5. Apply. `autoDeploy` is off, so later pushes do not redeploy.

## Verify

The worker log has one JSON line per cycle. Expected sequence:
- an early cycle submits `traitbank-darwin_1862_batch`; both of its jobs settle `DELIVERED`
  (`repository_evidence_reader_v1`, `traitbank_batch_validator_v1`);
- each later cycle reconciles the previous program and submits the next item;
- after the manifest drains, cycles report healthy `no_eligible_work`.

Against the acceptance database:

```sql
-- every cycle, newest first: productive, or a named healthy/defect category
SELECT sequence, productive, category, healthy, productive_jobs, finished_at
FROM calyx_program_autonomy_cycles ORDER BY finished_at DESC LIMIT 30;

-- the scientific job and its verdict
SELECT job_key, status, outcome,
       evidence_json::json -> 'output' -> 'results' AS verdict
FROM calyx_engineering_program_jobs
WHERE role_key = 'traitbank_batch_validator';

-- no job delivered twice
SELECT job_key, count(*) FROM calyx_engineering_program_jobs
GROUP BY job_key HAVING count(*) > 1;
```

Pass criteria:
- at least 10 consecutive productive cycles;
- no `defect` category;
- the TraitBank verdict `valid: true` for the Darwin batch;
- the duplicate query returns zero rows;
- after drain, healthy `no_eligible_work`.

If the evidence JSON shape differs, inspect the row with `SELECT evidence_json`.
The verdict is at `evidence_json -> 'output' -> 'results'`.

## Known limits

- The Brain pulse ledger lives on the container's ephemeral disk. After a restart the
  worker resubmits from the top of the manifest. Calyx answers `idempotent_replay`
  for programs it already holds, so nothing re-executes. This is expected, not a defect.
- This is acceptance evidence on non-production infrastructure. It is not a
  production enablement.

## Stop and roll back

1. Render → the acceptance worker → **Suspend**, or Delete. On SIGTERM it exits
   0 after the current cycle.
2. Neon → delete the `oc-autonomy-acceptance` project (option A), or drop the
   acceptance database and role (option B).
3. Revoke the fine-grained token if it is no longer needed by CI.

The production service and database are untouched by construction.
