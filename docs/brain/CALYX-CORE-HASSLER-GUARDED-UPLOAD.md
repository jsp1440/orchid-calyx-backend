# CALYX CORE — Guarded Hassler production upload boundary

Date: 2026-08-09
Issue: #386
Parent: #384
PR: #734 (superseded by current PR)

## Status

IMPLEMENTED / EXECUTABLE-GREEN / READY FOR OWNER REVIEW OF THE TOOLING.

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

## Runtime dependency

`httpx` is declared as a runtime dependency in `requirements.txt`. The validation workflow installs from `requirements.txt` so CI matches the repository runtime manifest.

## Mutation-truth receipts

Receipt schema `1.2` prevents a post-mutation verification failure from disappearing as a generic exception.

- `NONE`: no upload request was issued.
- `CONFIRMED`: the upload response confirmed durable mutation.
- `UNKNOWN`: an upload request was issued but the HTTP/transport result could not establish whether production mutation occurred.

A confirmed upload followed by failed readback/readiness returns `MUTATED_VERIFICATION_FAILED` with `production_mutation=true`.

An indeterminate upload result returns `UPLOAD_RESULT_UNKNOWN` with `production_mutation=null` rather than falsely claiming no mutation.

Both failure receipts are hash-bound and cause non-zero CLI exit.

## Validation coverage

- Python compile;
- Ruff lint and format;
- normal upload/readback/replay/readiness behavior tests;
- confirmed-mutation/readback-failure receipt regression;
- unknown-upload-result receipt regression;
- governance smoke proving no staging/activation/KG authority and presence of both failure states.

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
