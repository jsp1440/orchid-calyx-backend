# CALYX CORE — Guarded Hassler production upload boundary

Date: 2026-08-09
Issue: #386
Parent: #384
PR: #734

## Status

IMPLEMENTED / EXECUTABLE-GREEN / READY FOR OWNER REVIEW OF THE TOOLING.

Executable-green code/workflow head: `34cb93bb5ab6a0b3010ee390f4bb504041666f59`.

This status does **not** authorize merge or a production upload.

## Purpose

Prepare the exact production upload/readback operation for the real Hassler release without executing it. This closes the engineering gap before the production intake write while preserving the explicit owner governance boundary.

## Canonical source identity

`WorldOrchids 26-08 (Aug 2 2026).csv`

- size: `11,529,836` bytes
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`
- version label: `26-08`
- acquisition date: `2026-08-02`

## Guarded operator client

`scripts/upload_hassler_release_guarded.py` is fail closed.

Dry-run is the default. A live upload requires `--execute`, the exact source identity, owner-session credentials, backend URL, and exact confirmation token `UPLOAD_WORLD_ORCHIDS_26_08`.

The client performs immutable readback **before mutation**:

1. authenticate through the owner-session endpoint;
2. read `GET /api/mission-control/taxonomy/releases/{EXPECTED_SHA256}`;
3. exact existing durable identity returns `NO_OP_ALREADY_PRESENT`, `upload_invoked=false`, `production_mutation=false`;
4. only a genuine 404 may proceed to live upload-readiness checks;
5. mismatched existing identity or any other response fails closed;
6. only after readiness confirms `upload_world_orchids_release` may the client issue `POST /api/mission-control/taxonomy/releases/inspect`;
7. a successful first upload must round-trip immutable identity and stop at staging-smoke readiness.

The client never calls staging or activation and always reports those authorities as false.

## Mutation-truth receipts

Receipt schema `1.2` prevents a post-mutation verification failure from disappearing as a generic exception.

- `NONE`: no upload request was issued.
- `CONFIRMED`: the upload response confirmed durable mutation.
- `UNKNOWN`: an upload request was issued but the HTTP/transport result could not establish whether production mutation occurred.

A confirmed upload followed by failed readback/readiness returns `MUTATED_VERIFICATION_FAILED` with `production_mutation=true`.

An indeterminate upload result returns `UPLOAD_RESULT_UNKNOWN` with `production_mutation=null` rather than falsely claiming no mutation.

Both failure receipts are hash-bound and cause non-zero CLI exit.

## Validation correction and coverage hardening

Recovered CI first exposed formatter drift only. Ruff-required wrapping was applied to the guarded client and its normal behavior tests without changing semantics.

A subsequent validation audit found a coverage gap: the dedicated workflow did not execute `tests/test_upload_hassler_release_guarded_failure_receipts.py` even though those receipt semantics are part of this branch. The existing workflow was therefore extended—not redesigned—to include the failure-receipt file in its path trigger, compile, Ruff lint/format, pytest execution, and governance smoke.

Exact head `34cb93bb5ab6a0b3010ee390f4bb504041666f59` passed all applicable workflows:

- CALYX Hassler Guarded Upload Client Validation run `31324140209` — success;
- CALYX Workflow Governance Audit `31324140289` — success;
- BUILD-088E Validation `31324140229` — success.

The dedicated gate passed:

- Python compile;
- Ruff lint and format;
- normal upload/readback/replay/readiness behavior tests;
- confirmed-mutation/readback-failure receipt regression;
- unknown-upload-result receipt regression;
- governance smoke proving no staging/activation/KG authority and presence of both failure states.

No unresolved review threads exist on PR #734.

CI contains no production credentials and uses mocked HTTP transport for upload behavior; validation performed no production POST.

## API/schema impact

No server API or database schema is added by this client. It consumes existing Mission Control owner-session, taxonomy release readback, taxonomy readiness, and release-inspect APIs.

The local receipt contract remains schema version `1.2` and adds truthful three-state production-mutation reporting around an already-defined guarded upload operation.

## Governance boundary

The first real upload is a production database mutation. Issue #386 explicitly requires agents to stop before merge and before production upload.

Therefore:

- the client may be reviewed as executable-green tooling;
- merge requires the owner-governed disposition required by #386;
- `--execute` against production is **not authorized** by this validation;
- bounded staging is a separate state-changing step;
- taxonomy activation, canonical species mutation, Knowledge Graph mutation, publication, deployment, and Azure actions remain separately blocked.
