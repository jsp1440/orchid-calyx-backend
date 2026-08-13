# CALYX-MATRIX-022 — Production durability deployment orchestrator

## Purpose

Provide one guarded, auditable command for the database/data-copy portion of Matrix durability deployment while preserving the separation between **schema/data preparation** and **persistent service activation**.

## Dry-run

```bash
python scripts/calyx_matrix_durability_deploy.py
```

Dry-run performs no writes. It reports DATABASE_URL availability, migration-file inventory, current integrated durability readiness, the exact operations `--apply` would perform, and the two durable-mode environment values that would be required only after a successful apply.

## Apply database/data-copy phase

```bash
python scripts/calyx_matrix_durability_deploy.py --apply
```

`--apply` performs, in order:

1. migration 612 — durable Matrix identification sessions;
2. migration 613 — durable immutable Matrix registry versions;
3. strict source-registry integrity inventory;
4. checksum-safe copy of missing immutable registry packages into PostgreSQL;
5. integrated post-apply readiness verification.

The command fails closed on missing DATABASE_URL, missing migration files, migration/database exceptions, unreadable or malformed registry packages, independently recomputed checksum failures, immutable-version checksum conflicts, incomplete registry copy, or failed post-apply activation readiness.

## What this command deliberately does not do

It does not modify Render/service environment variables and therefore does not persistently enable either durable store. It does not activate live Vision inference, publish knowledge, modify taxonomy, or modify scientific evidence.

After `activation_ready_after_apply=true`, persistent deployment configuration must set, in this order:

```text
CALYX_MATRIX_REGISTRY_DURABLE_ENABLED=true
CALYX_MATRIX_SESSION_DURABLE_ENABLED=true
```

Registry durability is enabled first because a durable session is not scientifically restart-reproducible if its exact immutable registry package remains ephemeral.

After service restart/redeploy, verify:

```text
GET /api/matrix-identification/persistence-readiness
```

Success requires `scientific_trail_durable_active=true` and no component blockers.

## Operational boundary

The repository can define, test, and review this procedure, but applying persistent environment configuration requires execution access to the production hosting environment. The GitHub connector alone cannot change Render service environment state.
