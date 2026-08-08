# CALYX occurrence persistence — issue #462

Date: 2026-08-07
Depends on: #461 taxonomy release intake and reviewed staging
Status: implementation DELIVERED for bounded deterministic validation; real production source runs remain intentionally unperformed.

## Goal

Provide the durable, bounded occurrence path required by the Accelerated Core without performing an unbounded harvest, taxonomy activation, production relinking, Knowledge Graph mutation, deployment, or publication.

Lifecycle implemented:

`bounded GBIF/iNaturalist records → immutable raw batch → deterministic normalization → reviewed-taxonomy reconciliation → unmatched/invalid review queue → resumable staging projection → readiness`

## Durable immutable raw intake

`runtime/occurrence_persistence.py` accepts only explicit caller-supplied bounded record arrays for `gbif` or `inaturalist`.

Limits are enforced before persistence:

- default maximum records: 5,000;
- default maximum serialized bytes: 25 MiB;
- each source record must contain a stable source identifier;
- duplicate source identifiers within a batch fail closed.

The canonical raw JSONL representation is SHA-256 addressed. A replay of identical content resolves to the same batch identity and cannot replace conflicting content.

No network harvester exists in this slice. `unbounded_harvest_authorized=false` is permanent.

## Deterministic normalization

Each normalized row preserves:

- source and source record ID;
- source row number;
- scientific name;
- supplied taxonomy key when present;
- exact reconciliation state and method;
- canonical taxon ID when an exact reviewed match exists;
- decimal latitude and longitude;
- coordinate uncertainty in meters;
- coordinate validity state;
- event date;
- country code;
- basis/quality record;
- full original source record;
- deterministic row SHA-256.

Invalid or partial coordinates are retained as evidence but are explicitly classified rather than silently accepted.

## Taxonomy reconciliation contract

Issue #462 depends on the reviewed taxonomy contract from #461. The occurrence service consumes only an operator-configured local taxonomy staging artifact:

`CALYX_TAXONOMY_REVIEW_STAGING_PATH`

The request cannot supply an arbitrary server path.

Reconciliation is intentionally conservative and deterministic:

1. exact supplied `taxon_key` match;
2. exact normalized scientific-name match;
3. ambiguous exact-name match enters review;
4. unmatched name enters review.

The #461 `taxon_key` is preserved as the `canonical_taxon_id` for this review-staging layer. This does not activate taxonomy and does not assert production canonical publication.

No fuzzy taxonomic inference is performed in occurrence persistence.

## Review queue

A deterministic read-only review queue is produced for records with:

- unmatched taxa;
- ambiguous taxa; or
- invalid coordinates.

Queue pagination is bounded. `review_write_authorized=false` is permanent in this surface; no human review decision is invented by the pipeline.

## Resumable idempotent staging

`project_staging()` processes normalized rows in bounded batches of 1–5,000. A durable checkpoint records:

- next offset;
- completion state;
- projected unique row count;
- normalized artifact digest.

Rows are keyed by row SHA-256 in the staging artifact, so completed replay has zero duplicate-row delta.

This staging artifact is review-only local state, not the production occurrence database or Knowledge Graph.

## Protected Mission Control API

`app/routers/occurrence_persistence.py` exposes owner/API-key protected routes under:

`/brain/mission-control/occurrences`

- `POST /intake` — bounded GBIF/iNaturalist batch intake;
- `POST /{batch_id}/stage` — bounded resumable staging projection;
- `GET /{batch_id}/review-queue` — bounded read-only review queue;
- `GET /{batch_id}/readiness` — deterministic readiness/evidence state.

The router is mounted through the existing live Mission Control router.

## Permanent non-authority

The readiness contract always returns:

- `ready_for_publication=false`;
- `knowledge_graph_mutation_authorized=false`;
- `taxonomy_activation_authorized=false`;
- `unbounded_harvest_authorized=false`.

The implementation contains no production graph writer, taxonomy activator, or live network harvester.

## Validation

Dedicated workflow:

`.github/workflows/calyx-occurrence-persistence-462.yml`

Validation covers:

- Python compilation;
- deterministic GBIF normalization and exact taxonomy reconciliation;
- immutable raw preservation;
- iNaturalist unmatched review behavior;
- coordinate uncertainty and invalid-coordinate classification;
- bounded intake enforcement;
- duplicate source-ID rejection;
- configured taxonomy staging fail-closed behavior;
- resumable projection;
- replay idempotency;
- protected Mission Control API;
- permanent non-authority assertions;
- changed-surface Ruff and diff hygiene;
- #461 taxonomy intake regression tests.

## Integration and dependency posture

This implementation is intentionally stacked on #461 because it consumes the reviewed taxonomy staging identity contract introduced there. The authoritative pull request for #462 should target the #461 feature branch until #461 is merged or otherwise resolved.

If #461 changes its reviewed canonical identity contract, #462 must be rebased and reconciliation tests rerun before retargeting to `main`.

## Explicit non-actions

This work does not:

- harvest GBIF or iNaturalist over the network;
- fabricate occurrence counts;
- activate a taxonomy release;
- relink production records;
- write to production occurrence tables;
- mutate `oc_graph`;
- publish scientific conclusions;
- deploy;
- merge.

Real production occurrence acquisition remains a separate governed operation after this bounded persistence path is reviewed and merged through the normal control plane.
