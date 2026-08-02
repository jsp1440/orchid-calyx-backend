# CALYX-TAXONOMY-ACTIVATION-001

## Purpose

Certify the deployed World Plants / Hassler intake path before Michael Hassler's production taxonomy file is uploaded. This procedure activates staging and inspection only. It never promotes a release or relinks downstream records.

## Required Render configuration

- `CALYX_TAXONOMY_INTAKE_DIR` points to a mounted persistent volume.
- `CALYX_TAXONOMY_STORAGE_PERSISTENT=true` only after the mount has been verified writable and persistent across a restart.
- `DATABASE_URL` points to the intended deployed PostgreSQL database.
- Owner authentication is configured and the protected GitHub `production` environment contains `CALYX_OWNER_ACCESS_CODE`.
- GitHub environment variable `CALYX_BACKEND_URL` points to the deployed backend.

Do not use `/tmp` as the certified production intake directory.

## Activation sequence

1. Deploy current backend `main` containing the merged taxonomy intake chain.
2. Mount the persistent taxonomy volume and verify write/read behavior.
3. Dispatch `CALYX-TAXONOMY-ACTIVATION-001` with `apply_staging_migration=true` and `run_live_smoke=false`.
4. Review the migration output. It applies `migrations/WORLD-PLANTS-STAGING-001.sql` twice and verifies all expected `oc_source` tables.
5. Set `CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED=true` in the deployed service only after step 4 succeeds.
6. Dispatch the workflow with `run_live_smoke=true`. It uploads only `tests/fixtures/world_plants_activation_smoke.csv`, reads the release back, verifies release listing, and calls the live readiness endpoint.
7. Restart or redeploy the backend through the normal approved Render process.
8. Confirm the smoke release still appears through the authenticated release detail and listing endpoints. Repeat the smoke workflow after restart if needed.
9. Set `CALYX_TAXONOMY_SMOKE_FIXTURE_VERIFIED=true` only after persistence across restart is proven.
10. Run the smoke workflow once more and retain the `calyx-taxonomy-readiness` artifact.

## Certification result

The production taxonomy file may be uploaded for inspection only when the live report contains:

```json
{
  "ready_for_upload": true,
  "ready_for_promotion": false
}
```

Every upload gate except `owner_promotion_approval` must report `passed`.

## Prohibited actions

This activation does not authorize:

- uploading `WorldOrchids 26-08 (Aug 2 2026).csv` before certification;
- changing the canonical taxonomy;
- accepting ambiguous mappings;
- relinking images, occurrences, literature, traits, interactions, conservation records, profiles, or graph edges;
- deleting historical releases;
- setting verification flags based only on unit tests or CI;
- promoting any staged release.

## After certification

Upload the real August 2026 release through Mission Control → Taxonomy Releases. Preserve the resulting checksum, inspection report, comparison report, synonym-review report, downstream-impact audit, and promotion blockers. Promotion remains a separate owner-governed operation.
