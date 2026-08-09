# CALYX CORE — Guarded Hassler production upload boundary

Date: 2026-08-08
Issue: #386
Parent: #384
Current-main replacement for stale PR #661

## Purpose

Prepare the exact production upload/readback operation for the real Hassler release without executing it. This closes the remaining engineering gap before the production intake write while preserving the explicit owner governance boundary.

## Canonical source identity

The canonical source is:

`WorldOrchids 26-08 (Aug 2 2026).csv`

Verified source identity:

- size: `11,529,836` bytes
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`
- version label: `26-08`
- acquisition date: `2026-08-02`

The previous #661 implementation validated this exact source identity and the guarded upload/readback behavior, but its branch later became non-mergeable as `main` advanced. This slice rebuilds the same bounded operator client directly on current `main` rather than forcing stale history.

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

The stale #661 exact head previously passed its focused workflow, workflow-governance audit, BUILD-088E, and an actual source dry-run identity check. This current-main replacement must independently pass its own exact-head validation before it can be considered ready.

## Current validation state

PR #734 was opened from current `main` at base `7f5bec2fb8092739a8e5fc5ce55ebc9008a9171e` with initial head `5793a42acfb0a37a7f6c45a5eee5c160d67bec90`.

Its first hosted validation attempts were created but failed before runner checkout. The dedicated `CALYX Hassler Guarded Upload Client Validation` run `31290720716` produced job `93187237107` with `steps=null`; BUILD-088E and Workflow Governance on the same head showed the same infrastructure pattern. This is tracked as the repository hosted-runner incident and is not counted as compile/lint/test evidence.

The implementation remains draft and unmerged until an exact unchanged head obtains executable CI and passes the focused validation plus BUILD-088E. No production upload or staging action was attempted.

## Governance boundary

This implementation does **not** authorize or perform the production upload. The upload stores immutable release bytes and metadata in the production `taxonomy_pipeline` schema, so it is a production database mutation requiring explicit owner approval separate from generic autonomous implementation instructions.

After an authorized upload/readback succeeds, bounded staging smoke remains a separate state-changing step. Taxonomy activation, canonical species mutation, Knowledge Graph mutation, and scientific publication remain independently blocked.

## Required disposition

Issue #386 explicitly requires agents to stop before merge and before production upload. Therefore this current-main replacement may be implemented and validated autonomously, but merge and production execution remain governance boundaries requiring an explicit owner decision.
