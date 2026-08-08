# CALYX taxonomy — production upload-ready evidence receipt

Date: 2026-08-08
Issue: #386
Main: `d63b6d616208d4189bd2662522bd7e156c2ce717`

## Status

The engineering path to production taxonomy intake is clear through the upload boundary.

Post-#650 authenticated read-only deployed discovery reports:

- migration 107 state: `migration_verified`;
- migration schema complete: `true`;
- durable PostgreSQL intake available;
- `ready_for_upload=true`;
- pipeline state: `ready_for_release_upload`;
- next job: `upload_world_orchids_release`;
- release count: `0`;
- exact Hassler release present: `false`;
- only remaining visible blocked gate: `smoke_fixture`;
- upload invoked: `false`;
- staging invoked: `false`;
- production mutation observed by this discovery: `false`;
- taxonomy activation authorized: `false`;
- Knowledge Graph mutation authorized: `false`.

The smoke gate is intentionally post-upload: it remains blocked until an inspected release exists, and it still prevents bounded staging after upload until smoke/readback verification succeeds.

## Canonical source proof

The exact owner Library source is available as:

`WorldOrchids 26-08 (Aug 2 2026).csv`

Verified metadata and local byte proof:

- size: `11,529,836` bytes;
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`.

This SHA-256 exactly matches the expected Hassler release identity already encoded in the production discovery contract. No filename-only substitution is required.

## Cleared blockers

The following prior blockers are now resolved:

1. GitHub Actions runner execution is healthy for the relevant taxonomy workflows.
2. Migration 107 is active and structurally verified in production.
3. Taxonomy intake no longer depends on a Render persistent filesystem volume; PostgreSQL source-byte storage is authoritative.
4. Readiness no longer depends on the stale `CALYX_TAXONOMY_STAGING_SCHEMA_VERIFIED` operator flag when live schema evidence is available.
5. The circular smoke-before-upload ordering defect is fixed and validated; upload/inspection now precedes smoke/readback.

## Remaining governance boundary

The next action changes production state: authenticated upload/inspection of the exact Hassler source into the durable PostgreSQL intake store.

That upload must preserve the exact verified SHA-256 and must not be coupled to taxonomy activation, publication, or Knowledge Graph mutation.

After upload, the required sequence is:

1. read back and verify the durable release identity and exact source metadata;
2. run the bounded smoke/readback gate;
3. only after successful smoke verification, allow a bounded staging batch;
4. inspect checkpoint/change-report/review evidence;
5. keep taxonomy activation and Knowledge Graph mutation separately blocked pending explicit governance.

No production upload or staging write is executed by this receipt.
