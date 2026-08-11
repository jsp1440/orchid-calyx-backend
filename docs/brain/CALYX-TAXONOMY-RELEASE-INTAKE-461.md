# CALYX taxonomy release intake — current-main convergence

Date: 2026-08-11
Issue: #461
Supersedes: historical intake PRs #598, #844, and stale current-main attempt #860
Status: implementation reconstructed on current canonical main; exact-head CI required before merge disposition.

## Purpose

Provide a review-only Hassler/WorldOrchids release intake path that preserves source identity, normalizes the real Hassler layout, builds bounded review/staging artifacts, and remains permanently unable to activate taxonomy or publish Knowledge Graph state.

## Current-main hardening

The reconstructed implementation includes three production-safety/data-integrity corrections found during review of the stale intake branch:

1. **Bounded multipart ingestion before materialization.** `UploadFile` is read incrementally and fails with HTTP 413 as soon as the configured maximum would be exceeded. Oversize content is not handed to `TaxonomyReleaseIntakeService` and no release workspace is created.
2. **UTF-8 BOM-safe header detection.** BOM-prefixed UTF-8 sources decode with `utf-8-sig`, so `Taxon` remains `Taxon` rather than becoming a corrupted first header and Hassler layout recognition remains deterministic.
3. **No minority-row truncation.** Canonical column expansion is based on the maximum observed physical row width, not the modal width. Wider minority Hassler rows therefore retain all repeated `Photo / Orientation / Author` slots. Metadata records modal width, maximum width, canonical width, and zero discarded overflow cells.

The protected taxonomy router is mounted into the then-current `live_mission_control.py` rather than copying a stale router version, preserving intervening canonical Mission Control work.

## Real August source identity

The acceptance target remains:

- filename: `WorldOrchids 26-08 (Aug 2 2026).csv` (operator artifact naming may vary only outside the immutable identity contract);
- size: 11,529,836 bytes;
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`;
- version label: `26-08`;
- acquisition date: `2026-08-02`.

The guarded production upload tooling is separate from this review/intake implementation. Merging this code does not upload the release.

## Intake contract

`runtime/taxonomy_release_intake.py` remains content-addressed and preserves immutable raw bytes. It supports generic headered taxonomy CSV and the recognized Hassler `Taxon / Number / Name` layout, including mixed UTF-8/legacy-byte normalization, repeated media slots, Hassler rank/status derivation, embedded synonym accounting, row-level deterministic hashes, bounded review queues, and idempotent staging projections.

Protected Mission Control routes remain under:

`/brain/mission-control/taxonomy/releases`

with owner/API-key authentication for intake, bounded staging projection, review-queue reads, and readiness reads.

## Permanent governance boundary

The implementation permanently reports:

- `ready_for_promotion=false`;
- `taxonomy_activation_authorized=false`;
- `production_relink_authorized=false`;
- `knowledge_graph_publication_authorized=false`.

It contains no taxonomy activation, production relink, Knowledge Graph publication, scientific publication, deployment, or credential authority.

## Validation target

Exact-head CI must cover:

- compile of intake runtime/router/current Mission Control mount;
- full existing issue-461 deterministic intake/staging suite;
- oversize multipart 413-before-materialization regression;
- UTF-8 BOM header regression;
- minority-wide-row media preservation regression;
- Ruff lint + format;
- permanent non-authority assertions;
- exact base-to-head diff hygiene.

Only after those gates are green and review threads are resolved may the implementation be considered merge-ready. Production upload, staging activation, taxonomy activation, and downstream graph mutation remain separate explicit governance decisions.
