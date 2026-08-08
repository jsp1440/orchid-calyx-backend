# CALYX licensed media persistence — issue #463

Date: 2026-08-07
Depends on: #461 reviewed taxonomy staging; merged BUILD-BRAIN-111A artifact registry (PR #501)
Status: implementation delivered for bounded deterministic validation; no production media import or publication performed.

## Goal

Provide a durable, review-only path for licensed scientific media with explicit rights, attribution, provenance, taxon reconciliation, duplicate handling, resumable staging, and readiness evidence.

Lifecycle:

`bounded media metadata → rights/attribution validation → immutable raw batch → deterministic normalization → reviewed-taxonomy reconciliation → artifact-registry evidence registration → duplicate/ambiguity review → resumable staging → readiness`

## Rights and attribution controls

The service accepts only explicit caller-supplied records. Each record must provide:

- provider identity;
- valid HTTP(S) source URL;
- creator;
- attribution/credit text;
- allowlisted license;
- SHA-256 of the underlying media asset;
- media type;
- acquisition time.

Allowlisted rights classes are deliberately narrow: CC0 1.0, CC BY 3.0/4.0, CC BY-SA 3.0/4.0, and public-domain records. Unknown, proprietary, or insufficiently attributed media fail closed before staging.

## Artifact registry integration

This slice reuses the merged immutable artifact registry in `app/calyx_orchestrator/artifact_registry.py`; it does not create a competing registry. Each normalized media record produces a deterministic metadata artifact whose evidence URI is the source URL and whose stored metadata includes the provider and underlying media SHA-256. The registry contract validates source URI, license metadata, producer identity, immutable content identity, and evidence presence.

The durable media workspace separately preserves raw and normalized JSONL plus a registry snapshot. Artifact registration is evidence/provenance only and is not publication authority.

## Canonical taxonomy integration

The operator configures reviewed taxonomy staging through:

`CALYX_TAXONOMY_REVIEW_STAGING_PATH`

Requests cannot provide arbitrary server paths. Reconciliation is conservative:

1. exact supplied `taxon_key` match;
2. exact normalized scientific-name match;
3. ambiguous or unmatched identity enters review.

The review-stage canonical ID is the #461 `taxon_key`; this does not activate taxonomy or relink production records.

## Duplicate and ambiguity handling

Within a bounded batch the pipeline records review items for:

- duplicate source URL with identical checksum;
- one source URL associated with conflicting checksums;
- identical media checksum observed at different URLs;
- ambiguous taxon identity;
- unmatched taxon identity.

No duplicate or ambiguity is silently promoted. Review queue writes are not authorized by this surface.

## Bounded resumable staging

`project_staging()` projects normalized records in batches of 1–5,000. A durable checkpoint records the next offset, completion state, projected unique-row count, and normalized artifact digest. Stable row SHA-256 values make replay idempotent.

The staging artifact is local review state, not the production Knowledge Graph or production media store.

## Protected Mission Control API

Routes are owner/API-key protected under:

`/brain/mission-control/media`

- `POST /intake`
- `POST /{batch_id}/stage`
- `GET /{batch_id}/review-queue`
- `GET /{batch_id}/readiness`

The router is mounted through the existing live Mission Control router.

## Permanent non-authority

The readiness contract always returns:

- `ready_for_publication=false`;
- `publication_authorized=false`;
- `knowledge_graph_mutation_authorized=false`.

No production graph writer, public publisher, live image downloader, or autonomous rights decision is present.

## Validation plan

Dedicated workflow:

`.github/workflows/calyx-licensed-media-persistence-463.yml`

It validates compilation, deterministic media tests, #461 taxonomy regression tests, merged artifact-registry tests, permanent non-authority assertions, Ruff, and `git diff --check`.

Fixture coverage includes allowlisted licensing, attribution rejection, exact taxon reconciliation, unmatched review, duplicate URL/hash handling, conflicting checksum review, bounded staging, replay idempotency, protected routes, invalid metadata, and batch limits.

## Explicit non-actions

This work does not download live media, import a production media corpus, expose sensitive locality information, activate taxonomy, publish media, mutate the production Knowledge Graph, deploy, merge, or fabricate production counts.
