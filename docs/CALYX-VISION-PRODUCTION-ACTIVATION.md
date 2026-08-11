# CALYX Vision Production Activation

This runbook activates the already-merged Vision → Lexicon durable schema without enabling live Vision-provider inference or scientific publication authority.

## Preconditions

- PR #845 is merged.
- PR #847 is merged.
- GitHub `production` environment has `DATABASE_URL` and `CALYX_BACKEND_URL` secrets.
- The deployed backend is on a revision containing the Vision activation hardening.
- Do not set `CALYX_VISION_DURABLE_ENABLED=true` until the migration workflow has completed successfully.

## Step 1 — Apply the database schema

Run GitHub Actions workflow **CALYX Vision Production Activation** with the exact confirmation phrase:

`APPLY CALYX VISION MIGRATIONS`

The workflow applies, in one PostgreSQL transaction:

1. `migrations/20260811_vision_lexicon_bridge.sql`
2. `migrations/20260811_vision_lexicon_activation_hardening.sql`

It verifies all 12 required `oc_vision` tables and verifies that the figure review-state constraint accepts `MACHINE_GENERATED` while preserving the governed review vocabulary.

## Step 2 — Enable durable runtime selection

After Step 1 succeeds, set the backend deployment environment variable:

`CALYX_VISION_DURABLE_ENABLED=true`

Redeploy/restart the backend so the process reads the new environment value.

Do not enable an ephemeral-memory override in production.

## Step 3 — Verify capability status

Read:

`GET /api/vision-lexicon/status`

Expected activation state:

- durable persistence requested/selected;
- schema/migration ready;
- `migration_activated=true`;
- `live_inference_enabled=false` until a provider adapter is separately configured and approved;
- scientific safeguards remain enabled.

## Step 4 — Durable smoke test

Create a governed test Reference Image Set and Vision Analysis through the authenticated API, record their IDs, restart the backend, and retrieve them again. Successful retrieval after restart proves the runtime is using PostgreSQL rather than process-local memory.

No Candidate Knowledge promotion, publication, taxonomy activation, or production Knowledge Graph mutation is part of this test.

## Step 5 — Provider activation is separate

Only after durable persistence passes the restart smoke test should a real image-capable model/provider be configured. Provider credentials alone do not authorize scientific promotion or publication.
