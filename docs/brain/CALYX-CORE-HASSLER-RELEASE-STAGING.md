# CALYX CORE — Real Hassler release durable staging

Date: 2026-08-08
Issue: #386
Parent: #384

## Real acceptance source

This build was designed against the actual owner-supplied Michael Hassler release, not a one-row fixture:

`WorldOrchids 26-08 (Aug 2 2026).csv`

Observed immutable source evidence:

- bytes: `11,529,836`
- SHA-256: `e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f`
- source encoding: Latin-1 fallback required
- delimiter: pipe (`|`)
- supplied header width: 13 named fields
- actual data-row width: 22 fields for every non-empty data row
- data rows: 34,724
- parser issues: 0
- photo references: 8,572
- rank counts:
  - F: 1
  - SF: 5
  - T: 22
  - ST: 55
  - G: 732
  - S: 32,108
  - SS: 738
  - V: 1,040
  - FM: 23
- duplicate taxon identities: 1
  - `S | Gastrochilus wenchuanensis P. Y. Wu & C. Y. Zhou` occurs twice

The apparent 13-vs-22 width mismatch is legitimate source structure: the header names the first photo/orientation/author slot while the data export contains up to four repeated photo/orientation/author triplets. Existing `runtime/world_plants_ingest.py` already models the 22-field shape correctly.

## Implemented staging boundary

Migration `107_world_plants_release_staging.sql` creates the isolated `taxonomy_pipeline` schema:

- `releases` — immutable source checksum, metadata and exact source bytes;
- `staged_taxa` — versioned normalized source rows with deterministic row checksums;
- `staging_checkpoints` — durable resume position and staged count;
- `change_reports` — reviewed release-to-release comparison evidence;
- `review_queue` — explicit ambiguous or malformed taxonomic work.

`runtime/world_plants_staging.py` implements:

1. exact source-byte registration keyed by SHA-256;
2. bounded staging batches (maximum 2,000 rows per call);
3. durable checkpoint resume after process restart;
4. idempotent row upsert by release/source-row identity plus row checksum;
5. change reports covering added taxa, removed taxa, changed records, synonym changes, status changes, distribution changes and accepted-name change candidates;
6. conservative accepted-name-change detection only where a stable non-empty World Plants number exists in both releases;
7. explicit duplicate/malformed/accepted-name review items;
8. automatic report generation after the final staging batch.

Rows lacking a stable source number are never heuristically paired as renames. They remain explicit additions/removals for review. This preserves evidence/inference separation.

## Mission Control contract

The existing owner-authenticated upload remains:

`POST /api/mission-control/taxonomy/releases/inspect`

New owner-authenticated bounded staging endpoint:

`POST /api/mission-control/taxonomy/releases/{release_id}/stage`

New read-only staging/status endpoint:

`GET /api/mission-control/taxonomy/releases/{release_id}/staging`

The stage endpoint takes an already inspected release, verifies its checksum identity while registering exact source bytes in PostgreSQL, stages one bounded batch, returns the durable checkpoint and exposes the completed change report when available.

If migration 107 is not active, staging fails closed with an actionable 503 rather than falling back to ephemeral or production taxonomy mutation.

## Governance

This build deliberately does **not** implement an activation endpoint.

It does not:

- activate a taxonomy release;
- update the canonical production species tables;
- approve review-queue items;
- delete taxa from production;
- mutate `oc_graph` or the Knowledge Graph;
- publish scientific knowledge;
- run an unbounded staging operation;
- apply migration 107 to production.

Every response keeps `automatic_promotion=false`. Taxonomy activation remains an explicit owner governance boundary after review.

## Validation design

The dedicated `CALYX World Plants Durable Staging Validation` workflow uses disposable PostgreSQL 16 and verifies:

- additive isolated schema creation;
- immutable source-byte preservation;
- bounded staging and checkpoint resume;
- process/store restart recovery;
- replay produces zero new rows after completion;
- duplicate identities enter the review queue;
- accepted-name candidates require review;
- comparison categories remain evidence-backed;
- legacy Mission Control upload tests continue to pass;
- Ruff and compile pass;
- migration and runtime contain no `oc_graph` mutation;
- no automatic-promotion path exists.

Issue #386 requires an implementation PR and stop-before-merge. This build therefore remains unmerged even after exact-head validation succeeds.
