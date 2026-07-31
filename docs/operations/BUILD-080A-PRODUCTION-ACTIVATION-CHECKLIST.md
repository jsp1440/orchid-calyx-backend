# BUILD-080A — Institutional Archive Production Activation Checklist

## Purpose

Activate the merged Institutional Archive Manager safely without coupling archive ingestion to existing Knowledge Graph production tables.

## Preconditions

- [ ] `main` contains merge commit `4ee31a91602f8986fafba46ef11bde2ff64130e6` or a descendant.
- [ ] BUILD-080 Archive Validation run #12 (`30664980249`) remains successful.
- [ ] Staging and production `DATABASE_URL` values are confirmed separately.
- [ ] A current production database snapshot or rollback point exists.
- [ ] The deployment runtime includes PyYAML when YAML ingestion is required.
- [ ] Approved archive source roots are documented and enforced operationally.

## Staging migration

- [ ] Apply `migrations/106_institutional_archive_manager.sql` to staging.
- [ ] Confirm these tables exist:
  - `archive_documents`
  - `archive_files`
  - `archive_entities`
  - `archive_relationships`
  - `archive_import_runs`
  - `archive_provenance`
  - `archive_checkpoints`
- [ ] Reapply migration 106 and confirm idempotent completion.
- [ ] Verify no existing Knowledge Graph table definition changed.

## Staging API smoke tests

- [ ] `GET /archive/status` returns a valid response.
- [ ] `GET /archive/statistics` returns zero or expected archive-local counts.
- [ ] `GET /archive/documents` returns a valid paginated response.
- [ ] `GET /archive/entities` returns a valid paginated response.
- [ ] Unauthenticated `POST /archive/import` is rejected.
- [ ] Authenticated import of a small approved test directory succeeds.
- [ ] Duplicate re-import increments `duplicates_skipped` rather than creating a second document.
- [ ] A deliberately malformed file is logged while the run continues.
- [ ] A safe ZIP imports successfully.
- [ ] A ZIP path-traversal payload is rejected.
- [ ] Checkpoint state is written and visible.
- [ ] Resume completes an interrupted test run.

## Mission Control verification

- [ ] Mission Control displays files discovered.
- [ ] Mission Control displays files processed.
- [ ] Mission Control displays duplicates skipped.
- [ ] Mission Control displays documents indexed.
- [ ] Mission Control displays entities extracted.
- [ ] Mission Control displays relationships created.
- [ ] Mission Control displays elapsed time.
- [ ] Mission Control displays checkpoint status.

## Production activation

- [ ] Record the exact production database snapshot identifier.
- [ ] Apply migration 106 to production.
- [ ] Verify all seven archive tables and indexes.
- [ ] Deploy or restart the backend on the validated `main` revision.
- [ ] Confirm backend health before archive calls.
- [ ] Run read-only `/archive/status` and `/archive/statistics` smoke tests.
- [ ] Run one small, approved production import.
- [ ] Confirm provenance, manifest, duplicate handling and Mission Control counters.
- [ ] Do not enable unrestricted filesystem scanning.
- [ ] Do not connect archive export directly to production Knowledge Graph writes.

## Rollback boundary

The isolated rollback script removes the archive subsystem tables. It must not be run in production after valuable archive records exist unless those records have first been exported and the rollback has been explicitly approved.

## Completion record

Record:

- Activation date:
- Operator:
- Deployed commit:
- Staging database:
- Production snapshot identifier:
- Production migration result:
- Smoke-test result:
- First import run ID:
- Remaining risks:
