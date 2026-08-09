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

### Idempotent replay hardening

Static review of the initial current-main rebuild found a production-operator defect: the client checked the generic readiness next-job before checking whether the exact immutable release already existed. If the release had already been uploaded, Mission Control would correctly advance beyond `upload_world_orchids_release`, but the client would treat that healthy state as an error and could not prove a safe replay.

The corrected flow is now:

1. authenticate with the existing owner-session endpoint;
2. `GET /api/mission-control/taxonomy/releases/{EXPECTED_SHA256}` **before any mutating request**;
3. if the response is 200, require the exact durable PostgreSQL identity and return `NO_OP_ALREADY_PRESENT` with `upload_invoked=false` and `production_mutation=false`;
4. if the response is 404, and only 404, continue to the live upload-readiness gate;
5. any other response fails closed;
6. after a first upload, read back the exact release again and verify post-intake readiness.

An existing report with mismatched SHA/name/version/acquisition date, automatic promotion, or non-PostgreSQL durability is rejected before any POST.

Before a first upload the client requires live Mission Control to report `ready_for_upload=true` with next job `upload_world_orchids_release`.

The only production write it can invoke is:

`POST /api/mission-control/taxonomy/releases/inspect`

After a first upload it verifies:

- release ID equals the exact SHA-256;
- snapshot SHA-256 matches;
- filename/version/acquisition date match;
- durable storage is PostgreSQL;
- automatic promotion remains false;
- direct release readback returns the same identity;
- Mission Control advances only to `release_inspected_staging_smoke_required`;
- next job is `verify_taxonomy_staging_smoke`.

For an already-present exact release, the client does not force the pipeline backward to the upload state. It preserves and reports the server-current next job, which may legitimately be staging smoke, bounded staging, review, or a later governed state.

The client never calls the staging endpoint and records:

- `staging_invoked=false`;
- `taxonomy_activation_authorized=false`;
- `knowledge_graph_mutation_authorized=false`;
- `automatic_promotion=false`.

## Validation contract

`tests/test_upload_hassler_release_guarded.py` verifies:

- checksum drift fails closed;
- an automatic-promotion response is rejected;
- a first upload requires an initial 404 readback and live upload readiness;
- successful first upload must round-trip immutable release identity;
- successful first upload stops at staging-smoke readiness;
- exact already-present durable release returns deterministic no-op without POST;
- mismatched already-present release fails before POST;
- blocked readiness prevents upload entirely;
- no `/stage` request is issued.

`.github/workflows/calyx-hassler-guarded-upload-client-validation.yml` runs compile, Ruff, focused tests, and a governance smoke. It has no production credentials and cannot execute a real upload.

The stale #661 exact head previously passed its focused workflow, workflow-governance audit, BUILD-088E, and an actual source dry-run identity check. This current-main replacement must independently pass its own exact-head validation before it can be considered ready.

## Current validation state

PR #734 was opened from current `main` at base `7f5bec2fb8092739a8e5fc5ce55ebc9008a9171e`.

Its first hosted validation attempts were created but failed before runner checkout. The dedicated `CALYX Hassler Guarded Upload Client Validation` run `31290720716` produced job `93187237107` with `steps=null`; BUILD-088E and Workflow Governance on the same head showed the same infrastructure pattern. This is tracked as the repository hosted-runner incident and is not counted as compile/lint/test evidence.

The idempotent replay correction was implemented after that initial infrastructure-only run. The current branch must therefore receive fresh executable exact-head CI after the correction before it can be considered validated.

The implementation remains draft and unmerged. No production upload or staging action was attempted.

## Governance boundary

This implementation does **not** authorize or perform the production upload. The first upload stores immutable release bytes and metadata in the production `taxonomy_pipeline` schema, so it is a production database mutation requiring explicit owner approval separate from generic autonomous implementation instructions.

An exact already-present readback is read-only and results in `NO_OP_ALREADY_PRESENT`; it does not itself require a new mutation.

After an authorized first upload/readback succeeds, bounded staging smoke remains a separate state-changing step. Taxonomy activation, canonical species mutation, Knowledge Graph mutation, and scientific publication remain independently blocked.

## Required disposition

Issue #386 explicitly requires agents to stop before merge and before production upload. Therefore this current-main replacement may be implemented and validated autonomously, but merge and production execution remain governance boundaries requiring an explicit owner decision.
