# CONSERVATORY-MVP-001 — Dedicated Collection Foundation

## Completed

- Added an owner-gated `/api/conservatory` API independent of judging events.
- Added persistent mounted-volume storage through `CALYX_CONSERVATORY_DIR`.
- Added immutable plant IDs and sequential annual accession numbers (`OC-YYYY-NNNN`).
- Added stable QR identifiers (`calyx:plant:<uuid>`).
- Added plant list, detail, creation, and printable-label manifest endpoints.
- Added atomic writes, validation, persistence tests, API tests, and focused CI.

## Endpoints

- `GET /api/conservatory/plants`
- `POST /api/conservatory/plants`
- `GET /api/conservatory/plants/{plant_id}`
- `POST /api/conservatory/labels/manifest`

## Deployment requirement

Configure `CALYX_CONSERVATORY_DIR` on a persistent mounted volume. Do not begin production collection entry while this path points to an ephemeral filesystem.

## Governance and limitations

This build does not change canonical taxonomy or publish collection records. It does not yet implement photographs, histories, bulk CSV import, QR image rendering, Brother-specific print calibration, sharing, or matrix identification. The JSON store is an operational MVP boundary; a later PostgreSQL migration must preserve plant IDs, accession numbers, QR identifiers, and append-only history.

## Brain record

Priority decision: establish a reliable collection identity and label contract before adding richer histories or matrix integrations. The judging-event API is no longer the target data model for personal collection entry.
