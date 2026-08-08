# CALYX-631 — Immutable Research Station registered dataset rows

Date: 2026-08-08
Depends on: CALYX-453 Research Station and CALYX-617 Scientific Computing & Analysis Engine
Status: implementation branch pending exact-head validation; no merge, deployment, publication, or Knowledge Graph mutation authorized.

## Goal

Remove the Research Station Analysis Workbench's manual row-transport bottleneck without creating a second dataset identity or weakening CALYX-617's exact raw-dataset checksum binding.

Lifecycle:

`registered Research Station dataset metadata + checksum → authenticated owner-scoped row registration → exact canonical SHA verification → immutable private row artifact → authenticated row retrieval → existing CALYX-617 plan validation/execution`

## Contract

`runtime/research_dataset_rows.py` stores rows only for an existing Research Station project dataset. The submitted rows are canonicalized with the same stable JSON representation used by the CALYX-617 raw-row checksum contract.

Storage fails closed unless:

- the project and registered dataset exist under the authenticated owner scope;
- rows are a non-empty list of JSON-object records;
- row, column, and serialized-byte bounds are satisfied;
- provenance is explicit;
- the canonical rows SHA-256 exactly equals the dataset's already-registered `checksum_sha256`.

The dataset metadata remains the authority for dataset identity. The row store does not create or alter dataset IDs or checksums.

## Immutability and privacy

A successful row artifact records dataset/project identity, checksum, row and column counts, sorted column names, serialized byte count, provenance, rows, and governance flags.

Replay of the exact same artifact is idempotent. Any attempt to rewrite rows or provenance under the same registered dataset identity fails with an immutable-conflict error.

The artifact is private by default and exposes no publication or Knowledge Graph mutation authority.

## Protected API

Owner/API-key protected endpoints:

- `PUT /brain/mission-control/research/projects/{project_id}/datasets/{dataset_id}/rows`
- `GET /brain/mission-control/research/projects/{project_id}/datasets/{dataset_id}/rows`
- `GET /brain/mission-control/research/projects/{project_id}/datasets/{dataset_id}/rows/readiness`

The GET path revalidates stored row content against the registered dataset checksum before returning it, so storage drift fails closed.

## Bounds

Default bounded transport limits:

- 25,000 rows;
- 512 distinct columns;
- 10 MiB canonical serialized row payload.

These values bound the first browser/API transport surface and can be revisited only through an explicit later design change.

## Validation

Dedicated workflow `.github/workflows/calyx-research-dataset-rows-631.yml` compiles the row-store/router surface and runs:

- deterministic row checksum compatibility;
- immutable/replay-safe storage;
- checksum-mismatch rejection;
- immutable provenance conflict rejection;
- row bounds;
- readiness before/after row registration;
- protected owner-scoped PUT/GET API;
- CALYX-617 Analysis Plan regression suite;
- CALYX-453 Research Station regression suite;
- CALYX-448 Literature Intelligence regression suite;
- permanent private/non-authority assertions;
- Ruff and diff hygiene.

## Frontend integration target

The Research Station Workbench should retrieve the registered dataset's exact row artifact by project/dataset ID and pass those rows to the existing CALYX-617 plan validation, execution, and diagnostics endpoints. Manual row JSON can then become an explicit fallback/import path rather than the normal analysis transport.

## Governance

No public sharing, scientific publication, model selection, deployment, Knowledge Graph mutation, or merge authority is introduced by CALYX-631. This is a private deterministic transport/provenance layer only.
