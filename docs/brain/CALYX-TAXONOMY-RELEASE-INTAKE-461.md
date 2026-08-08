# CALYX taxonomy release intake — issue #461

Date: 2026-08-07
Base main: `c114aba0545a71a3be23375e5b6d84e624fa82b4`
Issue: #461
PR: #598 (draft; intentionally unmerged)
Status: implementation DELIVERED for synthetic/current-code validation; real August release evidence BLOCKED pending the exact source file.

## Goal

Provide the real-release-ready intake path for a caller-supplied Hassler WorldOrchids/World Plants release without inventing the August 2026 dataset and without giving repository code any taxonomy activation authority.

## Implemented

### Content-addressed immutable intake

`runtime/taxonomy_release_intake.py` accepts bounded caller-supplied bytes and derives a release identity from SHA-256. Source bytes are preserved under a content-addressed release directory. A replay of identical content resolves to the same release identity; a conflicting write cannot replace an existing immutable source.

The existing `runtime/taxonomy_preflight.py` remains the schema/file validator and candidate-vs-baseline comparison engine. Intake persists its preflight report rather than duplicating a second validator.

### Normalization and release evidence

Each source row is normalized into deterministic JSONL with:

- source row number;
- canonical `taxon_key` from the existing preflight identity rules;
- scientific name;
- normalized taxonomic status;
- accepted-name identifier when supplied;
- preserved normalized source record;
- deterministic row SHA-256.

The release manifest/readiness contract exposes:

- source SHA-256 and normalized artifact SHA-256;
- configured active-baseline filename and SHA-256 when present;
- preflight status/run identity;
- normalized row count;
- accepted-name count;
- synonym count;
- malformed-taxon count from the existing preflight findings;
- unresolved-review count;
- status counts;
- deterministic candidate-vs-baseline added/removed/changed comparison.

Only recognized accepted/synonym states escape taxonomy-status review. Unknown or unrecognized status values fail closed into `unresolved` rather than silently becoming new status classes.

### Active-release comparison

Mission Control reads the active comparison source only from operator configuration:

`CALYX_TAXONOMY_ACTIVE_BASELINE_PATH`

The upload request cannot supply an arbitrary server-side comparison path. If a configured baseline is missing or is not a regular file, intake fails closed instead of silently skipping comparison.

### Review queue

Rows are placed into a deterministic pending review queue when they have:

- no usable taxon identity;
- synonym status without an accepted-name identifier; or
- unresolved/unrecognized taxonomic status.

The service exposes bounded read-only queue pagination (offset >= 0, limit 1–500). `review_write_authorized=false` is permanent in this surface. No review decision is fabricated by the intake system.

### Bounded resumable staging projection

`project_staging()` projects normalized records into a local review staging artifact in batches of 1–5000 rows. A durable checkpoint records the next offset, normalized artifact digest, unique projected-row count, and completion state. Row digests make replay idempotent.

This staging artifact is intentionally not the production taxonomy database and does not relink downstream data.

### Protected Mission Control API

`app/routers/taxonomy_release_intake.py` exposes owner/API-key-protected routes under:

`/brain/mission-control/taxonomy/releases`

- `POST /intake` — bounded multipart source intake and configured-active-baseline comparison;
- `POST /{release_id}/stage` — bounded staging projection;
- `GET /{release_id}/review-queue` — bounded read-only review queue;
- `GET /{release_id}/readiness` — protected release evidence/readiness state.

The router is mounted through `app/routers/live_mission_control.py` and uses the existing `verify_owner_or_api_key` dependency.

### Permanent non-authority

Readiness can become `REVIEW_ONLY`; it cannot become taxonomy-promotion authority. The contract permanently returns:

- `ready_for_promotion=false`;
- `taxonomy_activation_authorized=false`;
- `production_relink_authorized=false`;
- `knowledge_graph_publication_authorized=false`.

No production DB connection or Knowledge Graph publisher is present in the intake service.

## Validation

Dedicated workflow:
`.github/workflows/calyx-taxonomy-release-intake-461.yml`

It provides:

- compile validation;
- deterministic synthetic intake/replay/comparison/review/staging tests;
- protected API route + configured active baseline + review-queue tests;
- permanent non-authority assertions;
- changed-surface Ruff and diff hygiene.

A first validation run (`31237084522`) proved compile, 6 functional tests and non-authority but caught Ruff import-format debt. A later expansion run (`31237320818`) caught a real semantic defect: an unfamiliar taxonomy status was not entering the unresolved queue. That classifier was repaired to fail unknown statuses into `unresolved`.

On owner-authored implementation head `525cb260cf47a56939f2ba6d146cc2c092361a0a`, all triggered validation lanes passed:

- CALYX Taxonomy Release Intake 461 `31237380172` — success;
- CALYX Workflow Governance Audit `31237380150` — success;
- BUILD-088E Validation `31237380173` — success;
- CALYX-AUTONOMY-DEPLOYMENT-001 `31237380141` — success;
- CALYX-SUPERVISED-PILOT-001 `31237380127` — success.

The dedicated lane passed compile, 7 deterministic tests, permanent non-authority assertions, Ruff, and `git diff --check`.

This Brain update creates the final owner-authored exact head; a fresh exact-head validation cycle after this documentation commit is required before #598 is considered internally validated. The PR still remains draft/unmerged regardless of CI because issue #461 explicitly says not to merge.

## External evidence still required

The exact `WorldOrchids 26-08 (Aug 2 2026).csv` source file has **not** been supplied in this repository context. Therefore this work does not claim:

- the August file checksum;
- its actual row count;
- added/removed/changed taxon counts for that release;
- accepted-name/synonym counts for that release;
- malformed/unresolved counts for that release;
- successful real-dataset staging completion;
- readiness for taxonomy promotion.

When the exact file is supplied, it can be run through this intake path and the existing preflight evidence controls. Promotion/activation remains a separate explicit governance operation.

## Explicit non-actions

This implementation does not activate taxonomy, relink production records, publish the Knowledge Graph, perform a production migration, deploy, provision Azure, or publish scientific conclusions. Issue #461 explicitly says not to merge; PR #598 remains draft/unmerged unless that issue-level governance instruction is separately changed.