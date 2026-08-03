# CALYX-TAXONOMY-ACTIVATION-002

## Purpose

Certify the deployed World Plants / Hassler intake path before the production taxonomy file is uploaded. This activates staging and inspection only. It never promotes a release or relinks downstream records.

## Required configuration

- `CALYX_TAXONOMY_INTAKE_DIR` points to persistent storage, not `/tmp`.
- `CALYX_TAXONOMY_STORAGE_PERSISTENT=true` only after persistence across restart is verified.
- `DATABASE_URL` points to the intended PostgreSQL database.
- The protected GitHub `production` environment contains `DATABASE_URL` and `CALYX_OWNER_ACCESS_CODE`.
- GitHub environment variable `CALYX_BACKEND_URL` points to the deployed backend.

## Activation sequence

1. Deploy current backend `main`.
2. Verify persistent taxonomy storage.
3. Dispatch `CALYX-TAXONOMY-ACTIVATION-002` with `apply_staging_migration=true` only.
4. Review the idempotent migration proof and expected `oc_source` tables.
5. Set `CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED=true` only after that proof succeeds.
6. Dispatch with `run_live_smoke=true`; only the committed one-row fixture is uploaded.
7. Restart or redeploy normally and verify the smoke release persists.
8. Set `CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED=true` only after restart persistence is proven.
9. Run the smoke workflow again and retain the readiness artifact.

## Required result

```json
{
  "ready_for_upload": true,
  "ready_for_promotion": false
}
```

## Prohibited actions

This workflow does not authorize production taxonomy upload before certification, canonical promotion, ambiguous mapping acceptance, downstream relinking, historical release deletion, or automatic verification flags.

After certification, the August 2026 Hassler file may be uploaded for inspection only. Promotion remains a separate owner-governed operation.
