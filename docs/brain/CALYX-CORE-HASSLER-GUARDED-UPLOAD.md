# CALYX CORE — Guarded Hassler production upload boundary

Date: 2026-08-08
Issue: #386
Parent: #384

## Purpose

Prepare the exact production upload/readback operation for the real Hassler release without executing it. This closes the remaining engineering gap before the production intake write while preserving the explicit owner governance boundary.

## Canonical source identity

The owner Library contains the canonical source:

`WorldOrchids 26-08 (Aug 2 2026).csv`

Verified source identity:

- size: `11,529,836` bytes
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`
- version label: `26-08`
- acquisition date: `2026-08-02`

Mission Control live discovery after PR #650 reports:

- migration 107 verified;
- `ready_for_upload=true`;
- pipeline state `ready_for_release_upload`;
- next job `upload_world_orchids_release`;
- release count `0`;
- real release absent;
- `smoke_fixture` remains blocked until upload/readback;
- no production mutation occurred during discovery.

## Guarded operator client

`scripts/upload_hassler_release_guarded.py` implements a fail-closed upload/readback client.

Dry-run is the default. A production upload requires all of:

1. `--execute`;
2. exact source filename;
3. exact source byte size;
4. exact source SHA-256;
5. `CALYX_BACKEND_URL`;
6. `CALYX_OWNER_ACCESS_CODE`;
7. exact confirmation token `CALYX_HASSLER_UPLOAD_CONFIRMATION=UPLOAD_WORLD_ORCHIDS_26_08`.

Before upload it authenticates through the existing owner session endpoint and requires live Mission Control to report `ready_for_upload=true` with next job `upload_world_orchids_release`.

The only production write it can invoke is:

`POST /api/mission-control/taxonomy/releases/inspect`

After upload it verifies:

- release ID equals the exact SHA-256;
- snapshot SHA-256 matches;
- filename/version/acquisition date match;
- durable storage is PostgreSQL;
- automatic promotion remains false;
- direct release readback returns the same identity;
- Mission Control advances only to `release_inspected_staging_smoke_required`;
- next job is `verify_taxonomy_staging_smoke`.

The client does not call the staging endpoint and records:

- `staging_invoked=false`;
- `taxonomy_activation_authorized=false`;
- `knowledge_graph_mutation_authorized=false`;
- `automatic_promotion=false`.

## Validation contract

`tests/test_upload_hassler_release_guarded.py` verifies:

- checksum drift fails closed;
- an automatic-promotion response is rejected;
- blocked readiness prevents upload entirely;
- successful upload must round-trip immutable release identity;
- successful upload stops at staging-smoke readiness;
- no `/stage` request is issued.

`.github/workflows/calyx-hassler-guarded-upload-client-validation.yml` runs compile, Ruff, focused tests, and a governance smoke. It has no production credentials and cannot execute a real upload.

## Governance boundary

This implementation does **not** authorize or perform the production upload. The upload stores immutable release bytes and metadata in the production `taxonomy_pipeline` schema, so it is a production database mutation requiring explicit owner approval separate from generic autonomous implementation instructions.

After an authorized upload/readback succeeds, bounded staging smoke remains a separate state-changing step. Taxonomy activation, canonical species mutation, Knowledge Graph mutation, and scientific publication remain independently blocked.

## Required disposition

Issue #386 states that agents open a PR and stop before merge. This slice therefore ends at a validated draft PR. No merge or production upload is authorized by this documentation.
