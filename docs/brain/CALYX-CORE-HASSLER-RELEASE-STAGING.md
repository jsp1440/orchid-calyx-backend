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

Row checksums are indexed but deliberately **not unique**. The real Hassler source contains a duplicate taxon identity, and source-row evidence must be preserved rather than silently deduplicated. Replay idempotency is enforced by `(release_id, source_row_number)` while duplicate identities remain visible to the review queue.

## Mission Control contract

The existing owner-authenticated upload remains:

`POST /api/mission-control/taxonomy/releases/inspect`

New owner-authenticated bounded staging endpoint:

`POST /api/mission-control/taxonomy/releases/{release_id}/stage`

New read-only staging/status endpoint:

`GET /api/mission-control/taxonomy/releases/{release_id}/staging`

The stage endpoint takes an already inspected release, verifies its checksum identity while registering exact source bytes in PostgreSQL, stages one bounded batch, returns the durable checkpoint and exposes the completed change report when available.

If migration 107 is not active, staging fails closed with an actionable 503 rather than falling back to ephemeral or production taxonomy mutation.

The existing owner-authenticated readiness endpoint now returns concrete workflow state and the next executable job without requiring the owner to know hashes, workflow names, or server paths. States include:

- `deployment_gates_blocking_intake` → `resolve_taxonomy_intake_gates`;
- `ready_for_release_upload` → `upload_world_orchids_release`;
- `release_inspected_staging_schema_blocked` → `verify_taxonomy_staging_schema` and explicit `production_database_migration` governance boundary;
- `release_inspected_staging_smoke_required` → `verify_taxonomy_staging_smoke`;
- `release_inspected_ready_for_bounded_staging` → `stage_next_taxonomy_batch` with maximum batch size 2,000.

The readiness module remains dependency-light and read-only. PostgreSQL dependencies are lazy-loaded only when durable staging endpoints are invoked, preserving existing lightweight readiness/upload validation environments.

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

Every response keeps `automatic_promotion=false`. Taxonomy activation remains an explicit owner governance boundary after review. Applying migration 107 to the production database is also recorded by Mission Control as a governance boundary rather than being performed implicitly.

## Validation design

The dedicated `CALYX World Plants Durable Staging Validation` workflow uses disposable PostgreSQL 16 and verifies:

- additive isolated schema creation;
- immutable source-byte preservation;
- bounded staging and checkpoint resume;
- process/store restart recovery;
- replay produces zero new rows after completion;
- duplicate source rows remain preserved while duplicate identities enter the review queue;
- accepted-name candidates require review;
- comparison categories remain evidence-backed;
- legacy Mission Control upload tests continue to pass;
- Ruff and compile pass;
- migration and runtime contain no `oc_graph` mutation;
- no automatic-promotion path exists.

## Validation history and corrective work

Validation was treated as a hard gate before expansion.

1. Legacy taxonomy workflows first exposed formatter-only differences in the router; formatting was corrected without changing behavior.
2. The readiness workflow then exposed a dependency regression because SQLAlchemy was imported eagerly by a previously dependency-light router. Durable staging dependencies were moved behind lazy imports, restoring the established upload/readiness contract.
3. The dedicated staging workflow exposed an import-layout Ruff violation; it was corrected.
4. Static review against the real release exposed an invalid unique row-checksum assumption. Because the real source contains duplicate taxon evidence, the checksum became a non-unique index while source-row identity remains the idempotency key.
5. The dedicated validation harness then exposed its own missing `httpx` test dependency; the harness was corrected rather than altering application code.
6. PostgreSQL staging tests subsequently passed, including duplicate-row preservation, restart/resume and replay behavior.
7. Mission Control readiness was extended with deterministic pipeline state and next-job reporting, then its formatting/test regressions were corrected before proceeding.

Exact implementation head validated before this Brain receipt: `3cb24c1e8d366142276f7caa7072985649bfb221`.

Successful exact-head runs:

- `CALYX World Plants Durable Staging Validation` run **#9** — success;
- `CALYX-TAXONOMY-READINESS-API-001` run **#14** — success;
- `WORLD-PLANTS-UPLOAD-001` run **#71** — success;
- `CALYX Workflow Governance Audit` run **#225** — success;
- `BUILD-088E Validation` run **#1126** — success.

This Brain update changes documentation only. The resulting documentation-bearing head must also pass the same applicable gates before the PR is considered review-ready.

## Current boundary

Issue #386 requires an implementation PR and stop-before-merge. PR #619 therefore remains open, draft, and unmerged even after exact-head validation succeeds.

The next production step would be application and verification of migration 107 so the real inspected release can enter durable bounded staging. That is a production database mutation and remains outside this autonomous implementation turn absent explicit owner approval. Taxonomy activation remains separately blocked until the completed change report and review queue have been reviewed and owner approval is explicitly recorded.
