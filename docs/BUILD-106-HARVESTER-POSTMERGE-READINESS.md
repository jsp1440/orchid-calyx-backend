# BUILD-106 — Harvester post-merge readiness

## Purpose

Validate the BUILD-093 operational harvesters and BUILD-105 safety controls after merge, without applying production migrations, enabling schedules, or running live source harvests.

## Automated validation

The BUILD-106 workflow compiles the focused harvester modules and runs:

```bash
pytest -q tests/test_build_105_harvester_safety.py
pytest -q \
  tests/test_build_093_harvester_migration.py \
  tests/test_build_093_gbif_checkpoint.py \
  tests/test_build_093_inat_checkpoint.py
```

The workflow uses a non-routable placeholder `DATABASE_URL`. The focused tests must mock database and source access and must not depend on a live PostgreSQL service or external API.

## Production migration gate

Do not apply `migrations/BUILD-105-harvester-safety.sql` until all of the following are true:

1. BUILD-106 focused CI passes on the exact release commit.
2. The migration is reviewed as additive and idempotent.
3. A database backup or recovery point exists.
4. The operator has confirmed the intended production `DATABASE_URL` target.
5. Harvester schedules remain paused during migration and smoke testing.

After approval, apply with transaction-stop behavior appropriate to the database client. Verify only these additive objects:

- `oc_admin.harvest_safety_state`
- `oc_admin.harvest_dead_letter`
- `harvest_dead_letter_harvester_created_idx`
- `harvest_dead_letter_unresolved_idx`

No target-table uniqueness constraints are part of BUILD-105.

## Controlled preview smoke tests

Use the authenticated no-write endpoint only after deployment:

```http
POST /api/harvesters/inaturalist/preview
POST /api/harvesters/gbif/preview
POST /api/harvesters/eol_traitbank/preview
```

Example request:

```json
{
  "mode": "audit_only",
  "limit": 25
}
```

Required assertions for every preview response:

- HTTP 200 for integrated harvesters
- `scheduled` is `false`
- `writes_enabled` is `false`
- `inserted` is `0`
- starting and ending checkpoints are equal
- no worker job is queued
- no target-table row counts change

GBIF preview must reject an offset window that would exceed 100,000 records.

## Live execution gate

Do not enable recurring production schedules in this build. A later owner-authorized build must establish:

- source-level request instrumentation
- persisted circuit-state restoration and pre-run checks
- per-source runtime and write budgets confirmed against staging behavior
- one manually authorized bounded live run per source
- rollback and pause procedure

## Rollback

Application rollback: redeploy the commit before BUILD-105/106 if the preview route or worker import fails.

Database rollback is normally unnecessary because the migration is additive. If removal is explicitly authorized and the tables contain no required audit history, drop the two BUILD-105 indexes and tables manually. Never remove them automatically.

## Current boundaries

This build does not:

- execute the migration
- contact GBIF, iNaturalist, or EOL
- run a production harvester
- enable or change schedules
- deploy services
- merge automatically
